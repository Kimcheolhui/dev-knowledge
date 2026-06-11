# Application Gateway for Containers Labs

작성일: 2026-06-04

이 폴더는 Application Gateway for Containers(AGC)를 Gateway API로 실습하기 위한 시나리오 모음이다. 기본 전제는 `01-application-gateway-for-containers.md`의 설치 가이드를 따라 ALB Controller, Gateway API CRD, BYO VNet/subnet, `ApplicationLoadBalancer` 또는 BYO AGC 리소스가 준비되어 있다는 것이다.

## 시나리오 구성

| 문서                                                                               | 포함 시나리오                                                    |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| [01-http-routing.md](01-http-routing.md)                                           | 기본 HTTP routing, hostname/path 기반 멀티 앱 라우팅             |
| [02-traffic-splitting-and-url-rewrite.md](02-traffic-splitting-and-url-rewrite.md) | weighted traffic splitting, URL rewrite                          |
| [03-https-and-cert-manager.md](03-https-and-cert-manager.md)                       | HTTPS termination, cert-manager 연계                             |
| [04-waf-and-observability.md](04-waf-and-observability.md)                         | WAF policy attachment, access/firewall logs, metrics/status 확인 |

## 공통 준비

실습 manifest는 `agc-lab` namespace와 `agc-lab-gateway` Gateway 이름을 기본으로 사용한다.

```bash
cd /home/cheolhuikim/studyspace/dev-knowledge/aks/gw-api/01-application-gateway-for-containers-labs

kubectl apply -f spec/00-namespace-and-apps.yaml
kubectl get pods,svc -n agc-lab
```

Gateway는 배포 전략에 따라 둘 중 하나만 적용한다.

Managed by ALB Controller 방식:

```bash
kubectl apply -f spec/01-gateway-managed.yaml
```

BYO 방식:

```bash
export AGC_RESOURCE_GROUP='<resource group for AGC resource>'
export AGFC_NAME='<Application Gateway for Containers resource name>'
export FRONTEND_NAME='<frontend resource name>'

export AGC_RESOURCE_ID=$(az network alb show \
  --resource-group $AGC_RESOURCE_GROUP \
  --name $AGFC_NAME \
  --query id -o tsv)

envsubst < spec/01-gateway-byo.yaml | kubectl apply -f -
```

Gateway 준비가 끝나면 다음 조건을 확인한다.

```bash
kubectl get gateway agc-lab-gateway -n agc-lab -o yaml
```

정상 상태에서는 `Accepted=True`, `Programmed=True`가 보이고, `status.addresses[0].value`에 AGC frontend FQDN이 들어간다.

## 공통 변수

실습 중 자주 쓰는 값은 다음처럼 잡아두면 편하다.

```bash
export LAB_NS=agc-lab
export GATEWAY_NAME=agc-lab-gateway
export FQDN=$(kubectl get gateway $GATEWAY_NAME -n $LAB_NS -o jsonpath='{.status.addresses[0].value}')
echo $FQDN
```

DNS가 아직 없으면 `curl --resolve`로 hostname routing을 검증한다.

```bash
export FQDN_IP=$(dig +short $FQDN | head -n 1)
curl -i --resolve app.example.com:80:$FQDN_IP http://app.example.com/
```

## Cleanup

시나리오별 route와 policy를 삭제한 뒤 공통 리소스를 삭제한다.

```bash
envsubst < spec/08-waf-policy.yaml | kubectl delete -f - --ignore-not-found
envsubst < spec/07-cert-manager-https-route.yaml | kubectl delete -f - --ignore-not-found
envsubst < spec/07-cert-manager-certificate.yaml | kubectl delete -f - --ignore-not-found
envsubst < spec/06-cert-manager-clusterissuer.yaml | kubectl delete -f - --ignore-not-found
kubectl delete -f spec/05-https-route.yaml --ignore-not-found
kubectl delete -f spec/05-gateway-https-managed.yaml --ignore-not-found
envsubst < spec/05-gateway-https-byo.yaml | kubectl delete -f - --ignore-not-found
kubectl delete -f spec/04-url-rewrite-route.yaml --ignore-not-found
kubectl delete -f spec/03-weighted-split-route.yaml --ignore-not-found
kubectl delete -f spec/02-basic-host-path-routes.yaml --ignore-not-found
kubectl delete -f spec/01-gateway-managed.yaml --ignore-not-found
envsubst < spec/01-gateway-byo.yaml | kubectl delete -f - --ignore-not-found
kubectl delete -f spec/00-namespace-and-apps.yaml --ignore-not-found
```
