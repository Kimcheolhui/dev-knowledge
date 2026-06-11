# 01. HTTP Routing

이 실습은 기본 HTTP routing과 hostname/path 기반 멀티 앱 라우팅을 한 번에 검증한다.

## 목표

- `Gateway` 하나로 HTTP listener를 만든다.
- 기본 route(`/`)가 `web-v1`으로 가는지 확인한다.
- `app.example.com/api`는 `api-v1`, `app.example.com/web`은 `web-v1`으로 라우팅한다.
- `store.example.com/`은 `store-v1`으로 라우팅한다.

## 전제 조건

- `README.md`의 공통 준비를 완료했다.
- `agc-lab-gateway`가 `Programmed=True` 상태다.
- 로컬에 `dig`와 `curl`이 있다. `dig`가 없다면 FQDN을 직접 DNS lookup할 수 있는 도구를 사용한다.

## 1. 샘플 애플리케이션 배포

```bash
kubectl apply -f spec/00-namespace-and-apps.yaml
kubectl rollout status deployment/web-v1 -n agc-lab
kubectl rollout status deployment/api-v1 -n agc-lab
kubectl rollout status deployment/store-v1 -n agc-lab
kubectl rollout status deployment/store-v2 -n agc-lab
```

## 2. Gateway 준비

Managed by ALB Controller 방식이면 다음을 적용한다.

```bash
kubectl apply -f spec/01-gateway-managed.yaml
```

BYO 방식이면 다음을 적용한다.

```bash
export AGC_RESOURCE_ID=$(az network alb show \
  --resource-group $AGC_RESOURCE_GROUP \
  --name $AGFC_NAME \
  --query id -o tsv)

envsubst < spec/01-gateway-byo.yaml | kubectl apply -f -
```

Gateway 상태를 확인한다.

```bash
kubectl wait --for=condition=Programmed gateway/agc-lab-gateway -n agc-lab --timeout=10m
kubectl get gateway agc-lab-gateway -n agc-lab -o wide
```

## 3. Route 적용

```bash
kubectl apply -f spec/02-basic-host-path-routes.yaml
```

Route 상태를 확인한다.

```bash
kubectl get httproute -n agc-lab
kubectl describe httproute basic-route -n agc-lab
kubectl describe httproute host-path-route -n agc-lab
kubectl describe httproute store-host-route -n agc-lab
```

각 route의 parent condition에서 `Accepted=True`, `ResolvedRefs=True`를 확인한다.

## 4. 기본 route 호출

```bash
export FQDN=$(kubectl get gateway agc-lab-gateway -n agc-lab -o jsonpath='{.status.addresses[0].value}')
curl -s http://$FQDN/ | jq .
```

기대 결과:

- `app` 값이 `web-v1`이다.
- `path` 값이 `/`다.

`jq`가 없다면 `curl -i http://$FQDN/`로 header와 body를 확인한다.

## 5. Hostname/path route 호출

DNS를 실제로 연결하지 않았다면 `--resolve`를 사용한다.

```bash
export FQDN_IP=$(dig +short $FQDN | head -n 1)

curl -s --resolve app.example.com:80:$FQDN_IP http://app.example.com/api/users | jq .
curl -s --resolve app.example.com:80:$FQDN_IP http://app.example.com/web/home | jq .
curl -s --resolve store.example.com:80:$FQDN_IP http://store.example.com/ | jq .
```

기대 결과:

- `app.example.com/api/users`는 `api-v1`으로 간다.
- `app.example.com/web/home`은 `web-v1`으로 간다.
- `store.example.com/`은 `store-v1`으로 간다.

## 6. 문제 확인 포인트

- `Gateway`에 address가 없다면 AGC frontend provisioning 또는 `ApplicationLoadBalancer`/BYO frontend 참조를 확인한다.
- `HTTPRoute`가 `Accepted=False`면 `parentRefs`, `hostnames`, listener `allowedRoutes`를 확인한다.
- `ResolvedRefs=False`면 Service 이름, namespace, port를 확인한다.
- `curl`이 연결되지 않으면 AGC frontend FQDN DNS lookup, NSG/UDR, BYO VNet peering을 확인한다.

## Cleanup

```bash
kubectl delete -f spec/02-basic-host-path-routes.yaml
```
