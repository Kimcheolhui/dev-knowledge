# 03. Cleanup

이 실습은 ndots lab 리소스를 삭제하고, 선택적으로 실행한 Zipkin port-forward를 종료한다.

## 0. 변수 설정

```bash
cd /home/cheolhuikim/studyspace/dev-knowledge/aks/coredns-lab/ndots/labs

export LAB_NS=ndots-lab
export LAB_ARTIFACT_ROOT="$PWD/artifacts"

if [[ -z "${LAB_RUN_ID:-}" && -d "$LAB_ARTIFACT_ROOT" ]]; then
  export LAB_ARTIFACT_DIR=$(find "$LAB_ARTIFACT_ROOT" -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)
else
  export LAB_RUN_ID=${LAB_RUN_ID:-$(date +%Y%m%d-%H%M%S)}
  export LAB_ARTIFACT_DIR="$LAB_ARTIFACT_ROOT/$LAB_RUN_ID"
fi

mkdir -p "$LAB_ARTIFACT_DIR"
echo "$LAB_ARTIFACT_DIR"
```

실행 결과 기록:

```text

```

## 1. Zipkin port-forward 종료

[02-verify-ndots-behavior.md](02-verify-ndots-behavior.md)에서 Zipkin 확인을 실행했다면 port-forward PID 파일이 남아 있다.

```bash
if [[ -f "$LAB_ARTIFACT_DIR/zipkin-port-forward.pid" ]]; then
  kill "$(cat "$LAB_ARTIFACT_DIR/zipkin-port-forward.pid")" 2>/dev/null || true
  rm -f "$LAB_ARTIFACT_DIR/zipkin-port-forward.pid"
else
  echo "No Zipkin port-forward PID file found in $LAB_ARTIFACT_DIR"
fi

pgrep -af "kubectl.*port-forward.*zipkin" || true
```

실행 결과 기록:

```text

```

## 2. Lab namespace 삭제

```bash
kubectl delete namespace "$LAB_NS" --wait=true
```

실행 결과 기록:

```text

```

## 3. 삭제 확인

```bash
kubectl get namespace "$LAB_NS" 2>&1 | tee "$LAB_ARTIFACT_DIR/cleanup-namespace-check.txt"
```

실행 결과 기록:

```text

```

기대 결과:

```text
Error from server (NotFound): namespaces "ndots-lab" not found
```
