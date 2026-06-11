# 04. WAF And Observability

이 실습은 AGC에 WAF policy를 연결하고, 운영 관점에서 상태/로그/메트릭을 확인하는 절차를 정리한다.

## 목표

- Azure WAF policy를 만들고 AGC Gateway API 리소스에 attach한다.
- WAF policy status와 route status를 확인한다.
- AGC access log, firewall log, metrics 수집을 활성화한다.
- Kubernetes status conditions와 ALB Controller 로그를 함께 확인한다.

## 전제 조건

- `01-http-routing.md`를 완료했고 `basic-route`가 있다.
- Azure CLI가 로그인되어 있고, 현재 subscription이 실습 대상 subscription이다.
- WAF policy와 diagnostic settings를 만들 수 있는 Azure RBAC 권한이 있다.
- Log Analytics workspace 또는 Storage Account 같은 diagnostic destination이 있거나 새로 만들 수 있다.

## 0. 공통 변수 수집

먼저 현재 subscription과 AKS/AGC 관련 값을 변수로 잡는다. 이미 `README.md`에서 설정했다면 그대로 재사용한다.

```bash
export SUBSCRIPTION_ID=$(az account show --query id -o tsv)
export AKS_NAME='<your AKS cluster name>'
export AKS_RESOURCE_GROUP='<your AKS resource group>'
export LAB_NS=agc-lab
export GATEWAY_NAME=agc-lab-gateway
```

현재 Gateway FQDN은 Kubernetes status에서 가져온다.

```bash
export FQDN=$(kubectl get gateway $GATEWAY_NAME -n $LAB_NS -o jsonpath='{.status.addresses[0].value}')
echo $FQDN
```

ALB Controller가 사용하는 managed identity도 확인한다. AKS add-on 방식이면 보통 `applicationloadbalancer-<cluster-name>` identity가 AKS node resource group에 생성된다.

```bash
export MC_RESOURCE_GROUP=$(az aks show \
  --name $AKS_NAME \
  --resource-group $AKS_RESOURCE_GROUP \
  --query nodeResourceGroup -o tsv | tr -d '\r')

az identity list \
  --resource-group $MC_RESOURCE_GROUP \
  --query "[?starts_with(name, 'applicationloadbalancer')].[name, principalId]" \
  -o table
```

출력된 identity 이름을 변수로 잡는다.

```bash
export ALB_IDENTITY_RESOURCE_GROUP=$MC_RESOURCE_GROUP
export ALB_IDENTITY_NAME=$(az identity list \
  --resource-group $ALB_IDENTITY_RESOURCE_GROUP \
  --query "[?starts_with(name, 'applicationloadbalancer')].name | [0]" \
  -o tsv)

export ALB_CONTROLLER_PRINCIPAL_ID=$(az identity show \
  --resource-group $ALB_IDENTITY_RESOURCE_GROUP \
  --name $ALB_IDENTITY_NAME \
  --query principalId -o tsv)

echo $ALB_IDENTITY_NAME
echo $ALB_CONTROLLER_PRINCIPAL_ID
```

Helm으로 ALB Controller를 설치했다면 위 자동 조회 대신 설치 때 사용한 identity를 직접 지정한다.

```bash
export ALB_IDENTITY_RESOURCE_GROUP='<identity resource group>'
export ALB_IDENTITY_NAME='azure-alb-identity'
export ALB_CONTROLLER_PRINCIPAL_ID=$(az identity show \
  --resource-group $ALB_IDENTITY_RESOURCE_GROUP \
  --name $ALB_IDENTITY_NAME \
  --query principalId -o tsv)
```

## 1. AGC resource ID 확인

BYO 방식이면 다음처럼 가져온다.

```bash
export AGC_RESOURCE_GROUP='<resource group for AGC resource>'
export AGFC_NAME='<Application Gateway for Containers resource name>'

export AGC_RESOURCE_ID=$(az network alb show \
  --resource-group $AGC_RESOURCE_GROUP \
  --name $AGFC_NAME \
  --query id -o tsv)
echo $AGC_RESOURCE_ID
```

Managed by ALB Controller 방식이면 `ApplicationLoadBalancer` status 또는 Azure Portal/Resource Graph에서 생성된 AGC resource ID를 확인한다.

```bash
kubectl get applicationloadbalancer alb-test -n alb-test-infra -o yaml
```

status message에 `alb-id=/subscriptions/.../providers/Microsoft.ServiceNetworking/trafficControllers/...` 형태가 표시될 수 있다.

다음 명령은 `ApplicationLoadBalancer` status에서 `alb-id=` 값을 추출한다. `jq`가 있으면 첫 번째 명령을, 없으면 두 번째 명령을 사용한다.

```bash
export ALB_NAME=alb-test
export ALB_NAMESPACE=alb-test-infra

export AGC_RESOURCE_ID=$(kubectl get applicationloadbalancer $ALB_NAME -n $ALB_NAMESPACE -o json \
  | jq -r '.status.conditions[]?.message | select(startswith("alb-id=")) | sub("^alb-id=";"")' \
  | head -n 1)

echo $AGC_RESOURCE_ID
```

```bash
export AGC_RESOURCE_ID=$(kubectl get applicationloadbalancer $ALB_NAME -n $ALB_NAMESPACE -o yaml \
  | sed -n 's/.*alb-id=\(\/subscriptions\/.*\)$/\1/p' \
  | head -n 1)

echo $AGC_RESOURCE_ID
```

AGC resource ID에서 resource group과 resource name을 역으로 계산할 수 있다.

```bash
export AGC_RESOURCE_GROUP=$(echo "$AGC_RESOURCE_ID" | awk -F/ '{for (i=1; i<=NF; i++) if ($i=="resourceGroups") {print $(i+1); exit}}')
export AGFC_NAME=$(echo "$AGC_RESOURCE_ID" | awk -F/ '{print $NF}')

echo $AGC_RESOURCE_GROUP
echo $AGFC_NAME
```

## 2. WAF/diagnostic 권한 사전 점검

WAF policy attachment에는 두 종류의 권한이 관련된다.

| 주체                            | 필요한 권한                                         | 확인 이유                                                                |
| ------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------ |
| 실습 실행자                     | WAF policy 생성 권한, diagnostic settings 생성 권한 | Azure WAF policy와 Azure Monitor diagnostic settings를 직접 만든다.      |
| ALB Controller managed identity | AGC 구성 권한, WAF policy read 권한                 | `WebApplicationFirewallPolicy` CR을 보고 AGC security policy를 구성한다. |

ALB Controller identity가 AGC resource에 대한 `AppGw for Containers Configuration Manager` 권한을 상속받는지 확인한다.

```bash
az role assignment list \
  --assignee $ALB_CONTROLLER_PRINCIPAL_ID \
  --scope $AGC_RESOURCE_ID \
  --include-inherited \
  -o table
```

`AppGw for Containers Configuration Manager`가 보이지 않으면 설치 가이드의 role assignment를 다시 확인한다. BYO 방식에서는 AGC resource group scope에 부여되어 있어야 한다.

WAF policy를 AGC resource group과 다른 resource group에 만들 경우, ALB Controller identity가 WAF policy를 읽을 수 있도록 `Reader` 권한을 WAF policy 또는 WAF policy resource group scope에 부여하는 것이 안전하다. 같은 resource group에 만들더라도 권한 문제가 의심되면 3번에서 `WAF_POLICY_ID`를 만든 뒤 Reader 권한을 추가한다.

Diagnostic settings를 만들 실행자는 AGC resource에 대해 `Microsoft.Insights/diagnosticSettings/write` 권한이 필요하다. 일반적으로 `Monitoring Contributor`, `Contributor`, `Owner` 중 하나면 충분하다. Log Analytics workspace나 Storage Account가 다른 resource group/subscription에 있으면 해당 destination에도 접근 권한이 필요하다.

현재 로그인한 사용자 기준 role assignment를 대략 확인한다.

```bash
export CURRENT_USER_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)

if [ -n "$CURRENT_USER_OBJECT_ID" ]; then
  az role assignment list \
    --assignee $CURRENT_USER_OBJECT_ID \
    --scope $AGC_RESOURCE_ID \
    --include-inherited \
    -o table
fi
```

## 3. WAF policy 생성

Azure Application Gateway WAF policy를 만든다. 실제 운영에서는 managed ruleset, mode, exclusions, custom rules를 조직 정책에 맞게 조정한다.

```bash
export WAF_RESOURCE_GROUP=${WAF_RESOURCE_GROUP:-$AGC_RESOURCE_GROUP}
export WAF_POLICY_NAME='agc-lab-waf'

az network application-gateway waf-policy create \
  --resource-group $WAF_RESOURCE_GROUP \
  --name $WAF_POLICY_NAME

export WAF_POLICY_ID=$(az network application-gateway waf-policy show \
  --resource-group $WAF_RESOURCE_GROUP \
  --name $WAF_POLICY_NAME \
  --query id -o tsv)

echo $WAF_POLICY_ID
```

WAF policy가 별도 resource group에 있거나 ALB Controller identity 권한이 확실하지 않다면 Reader 권한을 부여한다.

```bash
az role assignment list \
  --assignee $ALB_CONTROLLER_PRINCIPAL_ID \
  --scope $WAF_POLICY_ID \
  --include-inherited \
  -o table

az role assignment create \
  --assignee-object-id $ALB_CONTROLLER_PRINCIPAL_ID \
  --assignee-principal-type ServicePrincipal \
  --scope $WAF_POLICY_ID \
  --role Reader
```

## 4. WAF policy attachment 적용

`spec/08-waf-policy.yaml`은 `basic-route`에 WAF policy를 붙인다.

```bash
envsubst < spec/08-waf-policy.yaml | kubectl apply -f -
kubectl get webapplicationfirewallpolicy lab-waf-policy -n agc-lab -o yaml
```

기대 상태:

- `Accepted=True`
- `ResolvedRefs=True`
- `Programmed=True` 또는 `Deployment=True` 계열 condition

문제가 있으면 condition message를 먼저 본다.

```bash
kubectl describe webapplicationfirewallpolicy lab-waf-policy -n agc-lab
kubectl logs -n kube-system -l app=alb-controller --tail=200
```

## 5. WAF 동작 확인

정상 요청을 먼저 보낸다.

```bash
export FQDN=$(kubectl get gateway agc-lab-gateway -n agc-lab -o jsonpath='{.status.addresses[0].value}')
curl -i http://$FQDN/
```

탐지/차단 동작은 WAF policy mode와 rule 설정에 따라 다르다. 무리하게 공격 payload를 반복하기보다, 테스트용 rule 또는 낮은 위험도의 query string을 사용해 firewall log가 남는지 확인한다.

```bash
curl -i "http://$FQDN/?1=1=1"
```

응답이 즉시 차단되지 않더라도 Detection mode라면 firewall log에 기록될 수 있다.

## 6. Diagnostic destination 준비

Log Analytics workspace를 사용할 경우 기존 workspace를 쓰거나 실습용 workspace를 새로 만든다. 실습에서 새로 만들었다면 cleanup에서 지울 수 있도록 `CREATE_LAW=true`를 설정한다.

### 6.1 Log Analytics workspace 새로 만들기

AGC와 같은 region에 만드는 것을 권장한다. `AGC_LOCATION`은 AGC resource에서 가져온다.

```bash
export AGC_LOCATION=$(az resource show --ids $AGC_RESOURCE_ID --query location -o tsv)
export LOG_ANALYTICS_WORKSPACE_RG=${LOG_ANALYTICS_WORKSPACE_RG:-$AGC_RESOURCE_GROUP}
export LOG_ANALYTICS_WORKSPACE_NAME=${LOG_ANALYTICS_WORKSPACE_NAME:-agc-lab-law}
export CREATE_LAW=true

az monitor log-analytics workspace create \
  --resource-group $LOG_ANALYTICS_WORKSPACE_RG \
  --workspace-name $LOG_ANALYTICS_WORKSPACE_NAME \
  --location $AGC_LOCATION

export LOG_ANALYTICS_WORKSPACE_ID=$(az monitor log-analytics workspace show \
  --resource-group $LOG_ANALYTICS_WORKSPACE_RG \
  --workspace-name $LOG_ANALYTICS_WORKSPACE_NAME \
  --query id -o tsv)

echo $LOG_ANALYTICS_WORKSPACE_ID
```

### 6.2 기존 Log Analytics workspace 사용

기존 workspace를 사용할 경우 workspace name/resource group에서 resource ID를 가져온다. 기존 리소스는 cleanup에서 삭제하지 않도록 `CREATE_LAW=false`를 둔다.

```bash
export LOG_ANALYTICS_WORKSPACE_RG='<Log Analytics workspace resource group>'
export LOG_ANALYTICS_WORKSPACE_NAME='<Log Analytics workspace name>'
export CREATE_LAW=false

export LOG_ANALYTICS_WORKSPACE_ID=$(az monitor log-analytics workspace show \
  --resource-group $LOG_ANALYTICS_WORKSPACE_RG \
  --workspace-name $LOG_ANALYTICS_WORKSPACE_NAME \
  --query id -o tsv)

echo $LOG_ANALYTICS_WORKSPACE_ID
```

### 6.3 Storage Account destination 사용

Storage Account를 사용할 경우 storage account name/resource group에서 resource ID를 가져온다. Storage Account destination은 AGC와 같은 region이어야 한다.

```bash
export STORAGE_ACCOUNT_RG='<Storage Account resource group>'
export STORAGE_ACCOUNT_NAME='<storage account name>'

export STORAGE_ACCOUNT_ID=$(az storage account show \
  --resource-group $STORAGE_ACCOUNT_RG \
  --name $STORAGE_ACCOUNT_NAME \
  --query id -o tsv)

echo $STORAGE_ACCOUNT_ID
```

Storage Account에 firewall이 켜져 있다면 Azure Monitor diagnostic settings가 쓸 수 있도록 trusted Microsoft services bypass 설정도 확인한다.

```bash
az storage account show \
  --ids $STORAGE_ACCOUNT_ID \
  --query 'networkRuleSet.bypass' -o tsv
```

## 7. Diagnostic settings 활성화

먼저 사용 가능한 diagnostic category를 확인한다.

```bash
az monitor diagnostic-settings categories list \
  --resource $AGC_RESOURCE_ID \
  -o table
```

Log Analytics workspace로 보낼 경우:

```bash
az monitor diagnostic-settings create \
  --name agc-lab-diagnostics \
  --resource $AGC_RESOURCE_ID \
  --workspace $LOG_ANALYTICS_WORKSPACE_ID \
  --logs '[{"category":"TrafficControllerAccessLog","enabled":true},{"category":"TrafficControllerFirewallLog","enabled":true}]' \
  --metrics '[{"category":"AllMetrics","enabled":true}]'
```

Storage Account로 보낼 경우:

```bash
az monitor diagnostic-settings create \
  --name agc-lab-diagnostics-storage \
  --resource $AGC_RESOURCE_ID \
  --storage-account $STORAGE_ACCOUNT_ID \
  --logs '[{"category":"TrafficControllerAccessLog","enabled":true},{"category":"TrafficControllerFirewallLog","enabled":true}]' \
  --metrics '[{"category":"AllMetrics","enabled":true}]'
```

공식 문서 기준 diagnostic log를 처음 켠 뒤 실제 로그가 보이기까지 최대 1시간 정도 걸릴 수 있고, 일반 Azure Monitor diagnostic settings 문서는 최대 90분까지 지연될 수 있다고 설명한다.

## 8. Log Analytics에서 로그 확인

Log Analytics workspace를 사용한다면 다음 KQL로 access/firewall log 유입을 확인한다. 테이블 이름은 workspace의 resource-specific/table mode와 서비스 업데이트에 따라 달라질 수 있으므로, 먼저 `search`로 category를 찾는다.

```kusto
search "TrafficControllerAccessLog"
| take 20
```

```kusto
search "TrafficControllerFirewallLog"
| take 20
```

`AzureDiagnostics` 테이블에 들어오는 환경이라면 다음처럼 확인한다.

```kusto
AzureDiagnostics
| where ResourceProvider == "MICROSOFT.SERVICENETWORKING"
| where Category in ("TrafficControllerAccessLog", "TrafficControllerFirewallLog")
| order by TimeGenerated desc
| take 50
```

## 9. Kubernetes 상태 확인

Gateway/Route/Policy 상태를 같이 본다.

```bash
kubectl get gateway,httproute,webapplicationfirewallpolicy -n agc-lab
kubectl describe gateway agc-lab-gateway -n agc-lab
kubectl describe httproute basic-route -n agc-lab
kubectl describe webapplicationfirewallpolicy lab-waf-policy -n agc-lab
```

ALB Controller 로그도 확인한다.

```bash
kubectl logs -n kube-system -l app=alb-controller --tail=200
```

Helm 설치 방식으로 controller namespace를 바꿨다면 해당 namespace를 사용한다.

```bash
kubectl get pods -A -l app=alb-controller
```

## 10. 로그에서 볼 필드

Access log에서 주로 보는 필드:

- `clientIp`
- `hostName`
- `requestUri`
- `httpMethod`
- `httpStatusCode`
- `backendHost`, `backendIp`, `backendPort`
- `backendResponseLatency`, `timeTaken`
- `trackingId`

Firewall log에서 주로 보는 필드:

- `clientIp`
- `requestUri`
- `ruleSetType`, `ruleSetVersion`, `ruleId`
- `action`
- `message`, `details`
- `policyId`, `policyScope`, `trackingId`

`trackingId`는 AGC가 backend로 전달하는 `x-request-id`와 상관관계 분석에 쓸 수 있다.

## 11. Cleanup

```bash
envsubst < spec/08-waf-policy.yaml | kubectl delete -f - --ignore-not-found

az monitor diagnostic-settings delete \
  --name agc-lab-diagnostics \
  --resource $AGC_RESOURCE_ID

az monitor diagnostic-settings delete \
  --name agc-lab-diagnostics-storage \
  --resource $AGC_RESOURCE_ID
```

WAF policy 자체가 더 필요 없으면 삭제한다.

```bash
az network application-gateway waf-policy delete \
  --resource-group $WAF_RESOURCE_GROUP \
  --name $WAF_POLICY_NAME
```

실습에서 Log Analytics workspace를 새로 만들었다면 삭제한다. 기존 workspace를 사용했다면 삭제하지 않는다.

```bash
if [ "$CREATE_LAW" = "true" ]; then
  az monitor log-analytics workspace delete \
    --resource-group $LOG_ANALYTICS_WORKSPACE_RG \
    --workspace-name $LOG_ANALYTICS_WORKSPACE_NAME \
    --yes
fi
```

## 참고

- [Diagnostic logs for Application Gateway for Containers](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/diagnostics)
- [Application Gateway for Containers API specification for Kubernetes](https://learn.microsoft.com/en-us/azure/application-gateway/for-containers/api-specification-kubernetes)
