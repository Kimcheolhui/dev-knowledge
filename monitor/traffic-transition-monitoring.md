# 트래픽 전환 시 모니터링 포인트

> AKS 환경 기준

## 사전 준비

트래픽이 어떤 Deployment로 들어올지 사전에 파악해야 모니터링 구성을 미리 준비할 수 있다.

## 모니터링 대상

크게 두 가지로 나눌 수 있다.

1. **리소스 사용량**
2. **요청/응답 품질** (Status Code, Latency, Error Rate)

## 리소스 모니터링

### 클러스터 레벨

- Node의 CPU / Memory Utilization

### Deployment 레벨

- Pod의 CPU / Memory Utilization

트래픽 전환이 시작되면 Pod의 CPU Utilization은 당연히 증가한다. 이 증가가 정상 범위인지 판단하려면:

- 전체 Pod의 **평균** CPU Utilization이 적정 수준인지 확인
- **일부 Pod에만** 부하가 집중되고 있지는 않은지 확인

Memory도 반드시 함께 봐야 한다. Memory 초과 시 OOMKill이 발생하고, Pod 재시작으로 이어져 순간적인 서비스 장애가 될 수 있다.

- **Pod Restart Count**: 전환 후 Pod가 비정상적으로 재시작되고 있지 않은지 확인. CrashLoopBackOff, OOMKill 등을 빠르게 감지할 수 있는 지표다.

### Scaling 설정 파악

리소스 판단의 전제로, 현재 Scaling 구성을 알고 있어야 한다.

- **Node Scaling (Cluster Autoscaler)**: 어떻게 구성되어 있는지
- **Pod Scaling (HPA)**: min/max Pod 수, scaling 기준 metric

> Pod 수가 min 상태이면서 각 Pod의 Resource Utilization이 적정 수준 이하라면, 리소스 측면에서는 문제없다고 판단할 수 있다.

## 요청/응답 품질 모니터링

- **Response Status Code**: 4xx/5xx 비율 확인
- **Latency**: P50/P95/P99 응답 시간 확인. Status Code가 정상이어도 응답 시간이 크게 증가했다면 문제가 있는 것이다.
- **Error Rate 추이**: 단순 현재 값보다 전환 시점 전후의 **변화 추이**를 비교하는 것이 중요하다.

### 연관 서비스

해당 Deployment와 연관된 DB 등 외부 서비스의 metric도 함께 확인해야 한다.
