# AKS에서 Secret, ConfigMap 관리

## 개요

Azure Kubernetes Service (AKS)에서 애플리케이션을 운영할 때, 민감한 정보(비밀번호, API 키 등)와 설정 정보를 안전하고 효율적으로 관리하는 것은 매우 중요합니다. Kubernetes는 이를 위해 Secret과 ConfigMap이라는 두 가지 리소스를 제공합니다.

- **Secret**: 비밀번호, OAuth 토큰, SSH 키 등 민감한 정보를 저장
- **ConfigMap**: 애플리케이션 설정, 환경변수, 설정 파일 등 일반 설정 정보를 저장

## Secret과 ConfigMap의 차이

### Secret

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
type: Opaque
data:
  username: YWRtaW4=  # base64로 인코딩된 값
  password: cGFzc3dvcmQxMjM=
```

**특징**:
- Base64로 인코딩되어 저장 (암호화는 아님)
- 민감한 데이터 저장 용도
- 메모리에만 저장되어 디스크에 기록되지 않음
- RBAC(Role-Based Access Control)로 접근 제어 가능
- 최대 크기: 1MB

### ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  database_url: "postgres://localhost:5432/mydb"
  log_level: "info"
  config.json: |
    {
      "feature_flags": {
        "new_ui": true
      }
    }
```

**특징**:
- 평문(plain text)으로 저장
- 비민감한 설정 데이터 저장 용도
- 파일 형태로도 저장 가능
- 최대 크기: 1MB

## Secret 관리 방법

### 1. kubectl을 사용한 Secret 생성

#### 명령줄에서 직접 생성
```bash
# 리터럴 값으로 생성
kubectl create secret generic db-credentials \
  --from-literal=username=admin \
  --from-literal=password=password123

# 파일에서 생성
kubectl create secret generic tls-cert \
  --from-file=tls.crt=./cert.crt \
  --from-file=tls.key=./cert.key

# Docker registry 인증 정보
kubectl create secret docker-registry acr-secret \
  --docker-server=myregistry.azurecr.io \
  --docker-username=myuser \
  --docker-password=mypassword \
  --docker-email=user@example.com
```

#### YAML 파일로 생성

먼저 값을 base64로 인코딩합니다:
```bash
echo -n 'admin' | base64
# 결과: YWRtaW4=
echo -n 'password123' | base64
# 결과: cGFzc3dvcmQxMjM=
```

YAML 파일 작성:
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: db-credentials
  namespace: production
type: Opaque
data:
  username: YWRtaW4=
  password: cGFzc3dvcmQxMjM=
```

적용:
```bash
kubectl apply -f secret.yaml
```

### 2. Azure Key Vault와 연동

AKS에서 가장 권장되는 방법은 Azure Key Vault를 사용하는 것입니다. 이를 위해 CSI(Container Storage Interface) Secret Store Driver를 사용합니다.

#### Azure Key Vault Provider 설치

```bash
# CSI Secret Store Driver 설치
helm repo add csi-secrets-store-provider-azure https://azure.github.io/secrets-store-csi-driver-provider-azure/charts

helm install csi-secrets-store-provider-azure/csi-secrets-store-provider-azure \
  --generate-name \
  --namespace kube-system
```

#### SecretProviderClass 생성

```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: azure-kvname
  namespace: production
spec:
  provider: azure
  parameters:
    usePodIdentity: "false"
    useVMManagedIdentity: "true"
    userAssignedIdentityID: "<client-id>"
    keyvaultName: "my-key-vault"
    cloudName: ""
    objects: |
      array:
        - |
          objectName: db-username
          objectType: secret
          objectVersion: ""
        - |
          objectName: db-password
          objectType: secret
          objectVersion: ""
    tenantId: "<tenant-id>"
  secretObjects:
  - secretName: db-credentials
    type: Opaque
    data:
    - objectName: db-username
      key: username
    - objectName: db-password
      key: password
```

#### Pod에서 사용

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-pod
spec:
  containers:
  - name: app
    image: myapp:latest
    volumeMounts:
    - name: secrets-store
      mountPath: "/mnt/secrets-store"
      readOnly: true
    env:
    - name: DB_USERNAME
      valueFrom:
        secretKeyRef:
          name: db-credentials
          key: username
    - name: DB_PASSWORD
      valueFrom:
        secretKeyRef:
          name: db-credentials
          key: password
  volumes:
  - name: secrets-store
    csi:
      driver: secrets-store.csi.k8s.io
      readOnly: true
      volumeAttributes:
        secretProviderClass: azure-kvname
```

### 3. Sealed Secrets

GitOps 워크플로우에서 안전하게 Secret을 Git에 저장하려면 Sealed Secrets를 사용할 수 있습니다.

```bash
# Sealed Secrets Controller 설치
kubectl apply -f https://github.com/bitnami-labs/sealed-secrets/releases/download/v0.18.0/controller.yaml

# kubeseal CLI 설치
wget https://github.com/bitnami-labs/sealed-secrets/releases/download/v0.18.0/kubeseal-0.18.0-linux-amd64.tar.gz
tar xfz kubeseal-0.18.0-linux-amd64.tar.gz
sudo install -m 755 kubeseal /usr/local/bin/kubeseal
```

Secret을 SealedSecret으로 변환:
```bash
# Secret 생성
kubectl create secret generic db-credentials \
  --from-literal=username=admin \
  --from-literal=password=password123 \
  --dry-run=client -o yaml > secret.yaml

# SealedSecret으로 암호화
kubeseal -f secret.yaml -w sealed-secret.yaml

# Git에 안전하게 커밋 가능
git add sealed-secret.yaml
git commit -m "Add encrypted database credentials"
```

## ConfigMap 관리 방법

### 1. kubectl을 사용한 ConfigMap 생성

```bash
# 리터럴 값으로 생성
kubectl create configmap app-config \
  --from-literal=database_url=postgres://localhost:5432/mydb \
  --from-literal=log_level=info

# 파일에서 생성
kubectl create configmap app-config \
  --from-file=config.json \
  --from-file=application.properties

# 디렉토리의 모든 파일 포함
kubectl create configmap app-config \
  --from-file=./config-dir/
```

### 2. YAML 파일로 생성

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
  namespace: production
data:
  # 단순 키-값 쌍
  database_url: "postgres://localhost:5432/mydb"
  log_level: "info"
  max_connections: "100"
  
  # 파일 내용
  config.json: |
    {
      "server": {
        "port": 8080,
        "host": "0.0.0.0"
      },
      "features": {
        "new_ui": true,
        "beta_features": false
      }
    }
  
  application.properties: |
    spring.datasource.url=jdbc:postgresql://localhost:5432/mydb
    spring.jpa.hibernate.ddl-auto=update
    logging.level.root=INFO
```

### 3. Pod에서 ConfigMap 사용

#### 환경 변수로 사용
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-pod
spec:
  containers:
  - name: app
    image: myapp:latest
    env:
    # 개별 키를 환경 변수로
    - name: DATABASE_URL
      valueFrom:
        configMapKeyRef:
          name: app-config
          key: database_url
    # ConfigMap의 모든 키를 환경 변수로
    envFrom:
    - configMapRef:
        name: app-config
```

#### 볼륨으로 마운트
```yaml
apiVersion: v1
kind: Pod
metadata:
  name: app-pod
spec:
  containers:
  - name: app
    image: myapp:latest
    volumeMounts:
    - name: config-volume
      mountPath: /etc/config
  volumes:
  - name: config-volume
    configMap:
      name: app-config
      items:
      - key: config.json
        path: config.json
```

## 모노레포에서 K8s Spec 파일 관리

### 이미지 태그 관리 전략

모노레포에서 Kubernetes 스펙 파일을 관리할 때 가장 큰 고민은 이미지 태그 관리입니다. 주요 방법은 두 가지입니다:

#### 방법 1: Spec 파일에 이미지 태그를 직접 업데이트 (GitOps 방식)

```yaml
# deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qa-agent-api
spec:
  template:
    spec:
      containers:
      - name: app
        image: myregistry.azurecr.io/qa-agent-api:v1.2.3
```

**장점**:
- Git에서 배포 히스토리 추적 가능
- GitOps 도구(ArgoCD, Flux)와 완벽한 호환
- 선언적 방식으로 일관성 유지
- 롤백이 쉬움 (Git revert)

**단점**:
- CI/CD 파이프라인에서 YAML 파일 수정 필요
- 커밋이 많아질 수 있음
- Merge conflict 발생 가능

**구현 예시**:
```bash
# CI/CD 파이프라인에서
NEW_TAG="v1.2.3"

# yq를 사용한 이미지 태그 업데이트
yq eval ".spec.template.spec.containers[0].image = \"myregistry.azurecr.io/qa-agent-api:${NEW_TAG}\"" \
  -i k8s/deployment.yaml

# Git에 커밋
git add k8s/deployment.yaml
git commit -m "chore: update qa-agent-api to ${NEW_TAG}"
git push
```

#### 방법 2: kubectl set image 명령 사용 (Imperative 방식)

```yaml
# deployment.yaml (이미지 태그는 고정하지 않음)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qa-agent-api
spec:
  template:
    spec:
      containers:
      - name: app
        image: myregistry.azurecr.io/qa-agent-api:latest
```

**장점**:
- Spec 파일을 변경하지 않아 깔끔함
- 빠른 배포 가능
- Merge conflict 없음

**단점**:
- 배포 히스토리가 Git에 남지 않음
- GitOps 방식과 충돌
- 수동 롤백 필요
- 클러스터 상태와 Git 상태가 불일치

**구현 예시**:
```bash
# 새 이미지로 업데이트
kubectl set image deployment/qa-agent-api \
  app=myregistry.azurecr.io/qa-agent-api:v1.2.3 \
  -n production

# 롤아웃 상태 확인
kubectl rollout status deployment/qa-agent-api -n production

# 롤백
kubectl rollout undo deployment/qa-agent-api -n production
```

### 권장 방법: Kustomize 또는 Helm 사용

실전에서는 Kustomize나 Helm을 사용하여 이미지 태그를 외부에서 주입하는 방식을 권장합니다.

#### Kustomize 사용

```yaml
# base/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qa-agent-api
spec:
  template:
    spec:
      containers:
      - name: app
        image: qa-agent-api  # Kustomize가 치환할 플레이스홀더 이름
```

```yaml
# overlays/production/kustomization.yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- ../../base

images:
- name: qa-agent-api
  newName: myregistry.azurecr.io/qa-agent-api
  newTag: v1.2.3

namespace: production
```

배포:
```bash
# 이미지 태그 업데이트 (CI/CD에서)
cd overlays/production
kustomize edit set image qa-agent-api=myregistry.azurecr.io/qa-agent-api:v1.2.3

# 적용
kubectl apply -k overlays/production/
```

#### Helm 사용

```yaml
# values.yaml
image:
  repository: myregistry.azurecr.io/qa-agent-api
  tag: v1.0.0  # 배포 시 --set으로 오버라이드
  pullPolicy: IfNotPresent
```

```yaml
# templates/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}
spec:
  template:
    spec:
      containers:
      - name: app
        image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
        imagePullPolicy: {{ .Values.image.pullPolicy }}
```

배포:
```bash
# 이미지 태그를 파라미터로 전달
helm upgrade --install qa-agent-api ./helm-chart \
  --set image.tag=v1.2.3 \
  --namespace production
```

### 하이브리드 접근법

많은 팀이 사용하는 실전 전략:

1. **기본 스펙은 Git에서 관리** (GitOps)
2. **이미지 태그만 동적으로 업데이트**

```bash
# CI/CD 파이프라인
BUILD_TAG="v1.2.3-${CI_COMMIT_SHA:0:7}"

# 1. 이미지 빌드 및 푸시
docker build -t myregistry.azurecr.io/qa-agent-api:${BUILD_TAG} .
docker push myregistry.azurecr.io/qa-agent-api:${BUILD_TAG}

# 2. Kustomize로 이미지 태그 업데이트
cd k8s/overlays/production
kustomize edit set image qa-agent-api=myregistry.azurecr.io/qa-agent-api:${BUILD_TAG}

# 3. Git에 커밋 (선택적)
git add kustomization.yaml
git commit -m "chore: update image tag to ${BUILD_TAG}"
git push

# 4. ArgoCD가 자동으로 동기화하거나 수동 배포
# argocd app sync qa-agent-api
```

## 환경별 Secret/ConfigMap 관리

### Kustomize를 활용한 환경별 관리

```
k8s/
├── base/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   └── kustomization.yaml
├── overlays/
│   ├── dev/
│   │   ├── configmap.yaml
│   │   ├── secret.yaml
│   │   └── kustomization.yaml
│   ├── staging/
│   │   ├── configmap.yaml
│   │   ├── secret.yaml
│   │   └── kustomization.yaml
│   └── production/
│       ├── configmap.yaml
│       ├── secret.yaml
│       └── kustomization.yaml
```

**base/configmap.yaml**:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  log_level: "info"
```

**overlays/production/configmap.yaml**:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config
data:
  log_level: "warn"
  database_pool_size: "50"
```

**overlays/production/kustomization.yaml**:
```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

resources:
- ../../base

configMapGenerator:
- name: app-config
  behavior: merge
  literals:
  - environment=production

secretGenerator:
- name: db-credentials
  literals:
  - username=prod_user
  - password=prod_password
  type: Opaque

namespace: production
```

## 보안 모범 사례

### 1. Secret을 Git에 직접 커밋하지 않기

```bash
# .gitignore에 추가
*secret*.yaml
*.env
```

### 2. RBAC을 사용한 접근 제어

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: secret-reader
  namespace: production
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list"]
  resourceNames: ["db-credentials"]  # 특정 Secret만 허용
```

### 3. Secret 암호화 활성화

AKS에서 etcd 암호화를 활성화하여 Secret을 암호화된 상태로 저장:

```bash
# Azure CLI를 통한 활성화
az aks update \
  --resource-group myResourceGroup \
  --name myAKSCluster \
  --enable-encryption-at-host
```

### 4. Pod Security Standards 적용

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: production
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```

### 5. Secret 순환 (Rotation)

정기적으로 Secret을 교체하는 프로세스 구축:

```bash
# 새 Secret 생성
kubectl create secret generic db-credentials-new \
  --from-literal=username=admin \
  --from-literal=password=new_password123

# Deployment 업데이트
kubectl set env deployment/qa-agent-api \
  --from=secret/db-credentials-new \
  --prefix=DB_

# 이전 Secret 삭제
kubectl delete secret db-credentials
```

## ConfigMap 업데이트 시 Pod 재시작

ConfigMap이나 Secret을 업데이트해도 실행 중인 Pod는 자동으로 재시작되지 않습니다. 다음 방법을 사용하세요:

### 방법 1: Rollout 재시작

```bash
kubectl rollout restart deployment/qa-agent-api -n production
```

### 방법 2: Reloader 사용

[Reloader](https://github.com/stakater/Reloader)를 설치하면 ConfigMap/Secret 변경 시 자동으로 Pod를 재시작합니다:

```bash
# Reloader 설치
kubectl apply -f https://raw.githubusercontent.com/stakater/Reloader/master/deployments/kubernetes/reloader.yaml
```

Deployment에 어노테이션 추가:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qa-agent-api
  annotations:
    reloader.stakater.com/auto: "true"
    # 또는 특정 ConfigMap/Secret만 감시
    # configmap.reloader.stakater.com/reload: "app-config"
    # secret.reloader.stakater.com/reload: "db-credentials"
spec:
  template:
    spec:
      containers:
      - name: app
        image: qa-agent-api:v1.0.0
```

### 방법 3: ConfigMap을 해시값으로 버전 관리

Kustomize의 `configMapGenerator`를 사용하면 ConfigMap 이름에 자동으로 해시값이 추가되어 변경 시 자동으로 새 Pod가 생성됩니다:

```yaml
# kustomization.yaml
configMapGenerator:
- name: app-config
  literals:
  - log_level=info
generatorOptions:
  disableNameSuffixHash: false  # 해시 접미사 활성화
```

결과:
```yaml
# 생성된 ConfigMap 이름: app-config-k4h5m7b2f9
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-config-k4h5m7b2f9
data:
  log_level: info
```

## 실전 예제: 전체 워크플로우

### 시나리오: 새로운 마이크로서비스 배포

#### 1. Azure Key Vault에 Secret 생성

```bash
# Key Vault 생성
az keyvault create \
  --name my-key-vault \
  --resource-group myResourceGroup \
  --location koreacentral

# Secret 추가
az keyvault secret set \
  --vault-name my-key-vault \
  --name db-password \
  --value "SuperSecretPassword123!"

az keyvault secret set \
  --vault-name my-key-vault \
  --name api-key \
  --value "sk-1234567890abcdef"
```

#### 2. AKS 클러스터에 Managed Identity 연결

```bash
# Managed Identity 생성
az identity create \
  --name aks-keyvault-identity \
  --resource-group myResourceGroup

# Identity에 Key Vault 접근 권한 부여
az keyvault set-policy \
  --name my-key-vault \
  --object-id <identity-principal-id> \
  --secret-permissions get list
```

#### 3. K8s 리소스 작성

**k8s/base/configmap.yaml**:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: qa-agent-config
data:
  LOG_LEVEL: "info"
  PORT: "8080"
  ENVIRONMENT: "production"
```

**k8s/base/secret-provider.yaml**:
```yaml
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: azure-kv-provider
spec:
  provider: azure
  parameters:
    useVMManagedIdentity: "true"
    userAssignedIdentityID: "<identity-client-id>"
    keyvaultName: "my-key-vault"
    objects: |
      array:
        - |
          objectName: db-password
          objectType: secret
        - |
          objectName: api-key
          objectType: secret
    tenantId: "<tenant-id>"
  secretObjects:
  - secretName: app-secrets
    type: Opaque
    data:
    - objectName: db-password
      key: DB_PASSWORD
    - objectName: api-key
      key: API_KEY
```

**k8s/base/deployment.yaml**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: qa-agent-api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: qa-agent-api
  template:
    metadata:
      labels:
        app: qa-agent-api
    spec:
      containers:
      - name: api
        image: myregistry.azurecr.io/qa-agent-api:v1.0.0  # Kustomize/Helm으로 관리
        ports:
        - containerPort: 8080
        envFrom:
        - configMapRef:
            name: qa-agent-config
        env:
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: app-secrets
              key: DB_PASSWORD
        - name: API_KEY
          valueFrom:
            secretKeyRef:
              name: app-secrets
              key: API_KEY
        volumeMounts:
        - name: secrets-store
          mountPath: "/mnt/secrets"
          readOnly: true
        livenessProbe:
          httpGet:
            path: /health
            port: 8080
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8080
          initialDelaySeconds: 5
          periodSeconds: 5
      volumes:
      - name: secrets-store
        csi:
          driver: secrets-store.csi.k8s.io
          readOnly: true
          volumeAttributes:
            secretProviderClass: azure-kv-provider
```

#### 4. 배포

```bash
# Kustomize로 배포
kubectl apply -k k8s/overlays/production/

# 상태 확인
kubectl get pods -n production
kubectl logs -f deployment/qa-agent-api -n production

# Secret이 제대로 마운트되었는지 확인
kubectl exec -it deployment/qa-agent-api -n production -- ls -la /mnt/secrets
```

## 트러블슈팅

### 문제 1: Pod가 Secret을 읽지 못함

**증상**:
```
Error: secret "app-secrets" not found
```

**해결**:
```bash
# Secret이 올바른 네임스페이스에 있는지 확인
kubectl get secrets -n production

# Secret 내용 확인
kubectl describe secret app-secrets -n production

# RBAC 권한 확인
kubectl auth can-i get secrets --as=system:serviceaccount:production:default -n production
```

### 문제 2: ConfigMap 업데이트가 반영되지 않음

**증상**: ConfigMap을 업데이트했지만 애플리케이션이 이전 값을 사용함

**해결**:
```bash
# Pod 재시작
kubectl rollout restart deployment/qa-agent-api -n production

# 또는 ConfigMap을 볼륨으로 마운트한 경우, 자동 업데이트 시간 확인
# (기본적으로 약 60초 소요)
kubectl exec -it deployment/qa-agent-api -n production -- cat /etc/config/config.json
```

### 문제 3: Key Vault 접근 실패

**증상**:
```
Error: failed to get secret from keyvault: azure.BearerAuthorizer#WithAuthorization: 
Failed to refresh the Token for request
```

**해결**:
```bash
# Managed Identity가 올바르게 설정되었는지 확인
az aks show --resource-group myResourceGroup --name myAKSCluster --query identityProfile

# Key Vault 접근 정책 확인
az keyvault show --name my-key-vault --query properties.accessPolicies

# Pod에서 직접 테스트
kubectl exec -it deployment/qa-agent-api -n production -- sh
# 컨테이너 내부에서
curl -H "Metadata: true" "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://vault.azure.net"
```

## 요약

AKS에서 Secret과 ConfigMap을 효과적으로 관리하기 위한 핵심 포인트:

### Secret 관리
1. **Azure Key Vault 사용** - CSI Driver로 연동하여 중앙 집중식 관리
2. **Sealed Secrets** - GitOps 워크플로우에서 안전하게 Git 저장
3. **절대 평문으로 Git 커밋 금지**
4. **RBAC로 접근 제어**
5. **정기적인 Secret 순환**

### ConfigMap 관리
1. **환경별로 분리** - Kustomize overlay 사용
2. **버전 관리** - Git에서 추적
3. **업데이트 시 Pod 재시작** - Reloader 또는 수동 rollout
4. **해시 기반 이름** - ConfigMapGenerator로 자동 버전 관리

### 이미지 태그 관리
1. **GitOps 방식 권장** - Spec 파일에 태그 업데이트하여 Git 커밋
2. **Kustomize/Helm 사용** - 이미지 태그를 파라미터화
3. **kubectl set image는 임시 조치** - 프로덕션에서는 피하기
4. **태그에 커밋 SHA 포함** - 추적 가능성 확보

### 보안
1. etcd 암호화 활성화
2. Pod Security Standards 적용
3. Network Policies로 트래픽 제어
4. 정기적인 보안 스캔 및 업데이트
