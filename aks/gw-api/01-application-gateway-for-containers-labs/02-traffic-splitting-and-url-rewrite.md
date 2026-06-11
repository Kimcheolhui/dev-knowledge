# 02. Traffic Splitting And URL Rewrite

이 실습은 weighted traffic splitting과 URL rewrite를 함께 검증한다. 둘 다 배포 전환, A/B 테스트, backend path 호환성 유지에 자주 쓰는 기능이다.

## 목표

- `split.example.com` 요청을 `store-v1`과 `store-v2`로 80:20 비율로 분산한다.
- `rewrite.example.com/shop` 요청을 backend에는 `/ecommerce` 경로로 전달한다.
- rewrite 되지 않은 기본 요청은 `store-v2`로 보낸다.

## 전제 조건

- `01-http-routing.md`의 공통 앱과 Gateway 준비를 완료했다.
- `store-v1`, `store-v2` 서비스가 `agc-lab` namespace에 있다.

## 1. Weighted traffic splitting 적용

```bash
kubectl apply -f spec/03-weighted-split-route.yaml
kubectl describe httproute weighted-split-route -n agc-lab
```

`Accepted=True`, `ResolvedRefs=True`를 확인한다.

## 2. Weighted traffic splitting 테스트

```bash
export FQDN=$(kubectl get gateway agc-lab-gateway -n agc-lab -o jsonpath='{.status.addresses[0].value}')
export FQDN_IP=$(dig +short $FQDN | head -n 1)

for i in $(seq 1 20); do
  curl -s --resolve split.example.com:80:$FQDN_IP http://split.example.com/ | grep '"app"'
done
```

기대 결과:

- 대부분 `store-v1` 응답이 나온다.
- 일부 `store-v2` 응답이 섞인다.
- 소량 호출에서는 정확히 80:20으로 보이지 않을 수 있다. 충분히 많은 요청을 보내면 비율이 근접한다.

## 3. URL rewrite 적용

```bash
kubectl apply -f spec/04-url-rewrite-route.yaml
kubectl describe httproute url-rewrite-route -n agc-lab
```

## 4. URL rewrite 테스트

```bash
curl -s --resolve rewrite.example.com:80:$FQDN_IP http://rewrite.example.com/shop/cart | jq .
```

기대 결과:

- `app` 값은 `store-v1`이다.
- backend가 본 `path`는 `/ecommerce/cart`에 가까운 값이어야 한다.

기본 경로는 `store-v2`로 간다.

```bash
curl -s --resolve rewrite.example.com:80:$FQDN_IP http://rewrite.example.com/ | jq .
```

기대 결과:

- `app` 값은 `store-v2`다.
- `path` 값은 `/`다.

## 5. 문제 확인 포인트

- `weight`가 적용되지 않는 것처럼 보이면 요청 수를 늘린다.
- URL rewrite가 적용되지 않으면 `HTTPRoute.rules[].filters[].type`이 `URLRewrite`인지 확인한다.
- `ReplacePrefixMatch`는 `PathPrefix` match와 함께 쓰는 패턴으로 유지한다.
- route condition에 `Accepted=False`가 있으면 controller가 지원하지 않는 filter 조합을 사용했는지 확인한다.

## Cleanup

```bash
kubectl delete -f spec/03-weighted-split-route.yaml
kubectl delete -f spec/04-url-rewrite-route.yaml
```
