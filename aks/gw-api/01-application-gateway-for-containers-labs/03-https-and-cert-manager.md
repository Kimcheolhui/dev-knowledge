# 03. HTTPS And Cert-Manager

이 실습은 HTTPS termination과 cert-manager 연계를 다룬다. 먼저 self-signed certificate로 AGC HTTPS listener를 검증하고, 이후 Let's Encrypt + cert-manager로 실제 인증서 자동 발급 흐름을 검토한다.

## 목표

- Kubernetes TLS Secret을 사용해 AGC에서 HTTPS termination을 수행한다.
- `secure.example.com` HTTPS route를 검증한다.
- cert-manager Gateway API HTTP-01 solver를 사용해 `lab-tls` Secret을 자동 발급하는 흐름을 확인한다.

## 전제 조건

- `01-http-routing.md`의 공통 앱과 Gateway 준비를 완료했다.
- cert-manager 실습에는 실제 소유한 public DNS 도메인이 필요하다.
- Let's Encrypt HTTP-01 challenge를 위해 해당 도메인이 AGC frontend FQDN 또는 IP로 접근 가능해야 한다.

## 1. Self-signed 인증서로 HTTPS termination 검증

실제 인증서 자동화 전에 listener와 route 동작을 먼저 확인한다.

```bash
openssl req -x509 -nodes -days 7 -newkey rsa:2048 \
  -subj "/CN=secure.example.com/O=agc-lab" \
  -keyout /tmp/agc-lab.key \
  -out /tmp/agc-lab.crt

kubectl create secret tls lab-tls \
  -n agc-lab \
  --cert=/tmp/agc-lab.crt \
  --key=/tmp/agc-lab.key \
  --dry-run=client -o yaml | kubectl apply -f -
```

Managed by ALB Controller 방식:

```bash
kubectl apply -f spec/05-gateway-https-managed.yaml
```

BYO 방식:

```bash
envsubst < spec/05-gateway-https-byo.yaml | kubectl apply -f -
```

HTTPS route를 적용한다.

```bash
kubectl apply -f spec/05-https-route.yaml
kubectl wait --for=condition=Programmed gateway/agc-lab-gateway -n agc-lab --timeout=10m
```

## 2. HTTPS 호출 테스트

```bash
export FQDN=$(kubectl get gateway agc-lab-gateway -n agc-lab -o jsonpath='{.status.addresses[0].value}')
export FQDN_IP=$(dig +short $FQDN | head -n 1)

curl -k -i --resolve secure.example.com:443:$FQDN_IP https://secure.example.com/
```

기대 결과:

- HTTP status `200`을 받는다.
- 응답 body의 `app` 값은 `web-v1`이다.
- self-signed 인증서이므로 `curl -k`를 사용한다.

## 3. cert-manager 설치

cert-manager는 Gateway API solver를 사용해야 하므로 `config.enableGatewayAPI=true`로 설치한다.

```bash
helm install \
  cert-manager oci://quay.io/jetstack/charts/cert-manager \
  --version v1.19.3 \
  --namespace cert-manager \
  --create-namespace \
  --set config.enableGatewayAPI=true \
  --set crds.enabled=true

kubectl rollout status deployment/cert-manager -n cert-manager
kubectl rollout status deployment/cert-manager-webhook -n cert-manager
kubectl rollout status deployment/cert-manager-cainjector -n cert-manager
```

## 4. Let's Encrypt ClusterIssuer 생성

실제 이메일을 지정한다. 처음에는 staging endpoint를 쓰는 것도 좋다. `spec/06-cert-manager-clusterissuer.yaml`은 production endpoint를 기본으로 둔다.

```bash
export LETSENCRYPT_EMAIL='<your-email@example.com>'
envsubst < spec/06-cert-manager-clusterissuer.yaml | kubectl apply -f -
kubectl get clusterissuer letsencrypt-prod -o yaml
```

`Ready=True` 상태를 확인한다.

## 5. Certificate 생성

`LAB_DOMAIN`은 실제 소유한 도메인으로 바꾼다. 이 도메인은 AGC frontend로 라우팅되어야 한다.

```bash
export LAB_DOMAIN='<your-real-domain.example.com>'
envsubst < spec/07-cert-manager-certificate.yaml | kubectl apply -f -
kubectl get certificate lab-cert -n agc-lab
```

cert-manager는 HTTP-01 challenge 중 임시 `HTTPRoute`와 solver pod를 만든다. 실패하면 challenge 상태를 확인한다.

```bash
kubectl get challenges -n agc-lab
kubectl describe certificate lab-cert -n agc-lab
```

인증서 발급이 끝나면 `lab-tls` Secret이 갱신된다.

```bash
kubectl get secret lab-tls -n agc-lab
```

## 6. 실제 도메인용 HTTPS route 적용

Self-signed 실습의 `spec/05-https-route.yaml`은 `secure.example.com`을 사용한다. cert-manager 실습에서는 실제 도메인으로 route hostname을 맞춰야 한다.

```bash
envsubst < spec/07-cert-manager-https-route.yaml | kubectl apply -f -
kubectl describe httproute cert-manager-https-route -n agc-lab
```

## 7. cert-manager 인증서로 HTTPS 재검증

```bash
curl -v https://$LAB_DOMAIN/ 2>&1 | grep -E 'issuer|subject|SSL connection'
```

기대 결과:

- issuer가 Let's Encrypt 계열로 표시된다.
- `curl -k` 없이 HTTPS 연결이 성공한다.

## 8. 문제 확인 포인트

- HTTP-01 challenge는 public internet에서 도메인의 port 80으로 접근 가능해야 한다.
- DNS가 AGC frontend로 향하지 않으면 certificate 발급이 실패한다.
- Gateway의 HTTP listener가 없으면 cert-manager solver route가 challenge를 처리할 수 없다.
- AGC는 TLS 인증서를 Kubernetes Secret으로 참조한다. Secrets Store CSI driver로 외부 볼륨을 직접 mount하는 방식은 지원되지 않는다.

## Cleanup

```bash
envsubst < spec/07-cert-manager-https-route.yaml | kubectl delete -f - --ignore-not-found
kubectl delete -f spec/05-https-route.yaml --ignore-not-found
envsubst < spec/07-cert-manager-certificate.yaml | kubectl delete -f - --ignore-not-found
envsubst < spec/06-cert-manager-clusterissuer.yaml | kubectl delete -f - --ignore-not-found
kubectl delete secret lab-tls -n agc-lab --ignore-not-found
```
