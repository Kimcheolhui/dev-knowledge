# cgroup과 namespace 학습 가이드

이 문서는 Linux container의 기반이 되는 `cgroup`과 `namespace`를 학습하기 위한 정리 문서입니다. 단순 개념 설명이 아니라, 실제 Linux host 또는 VM에서 바로 확인할 수 있는 데모 흐름까지 포함합니다.

> 기준 환경: 최신 Linux 배포판에서 일반적으로 사용하는 **cgroup v2 unified hierarchy**를 중심으로 설명합니다. cgroup v1 예시는 역사적 배경이나 차이 설명에만 사용합니다.

---

## 1. 큰 그림

Container는 VM처럼 별도의 kernel을 가진 독립 OS가 아닙니다. 본질적으로는 **host Linux kernel 위에서 실행되는 process**입니다.

다만 container process에는 여러 kernel 기능이 함께 적용됩니다.

```text
container
= host 위의 process
+ namespace로 격리된 view
+ cgroup으로 제한된 resource
+ root filesystem 격리
+ capability/seccomp/AppArmor/SELinux 등 보안 제한
```

가장 중요한 두 축은 다음과 같습니다.

| 기능      | 핵심 역할               | 짧은 설명                                                                   |
| --------- | ----------------------- | --------------------------------------------------------------------------- |
| cgroup    | Resource control        | process group이 CPU, memory, pids, I/O 등을 얼마나 사용하는지 계측하고 제한 |
| namespace | Resource view isolation | process가 보는 PID, mount, network, hostname, cgroup path 등의 view를 격리  |

한 줄로 정리하면 다음과 같습니다.

```text
cgroup은 “얼마나 쓸 수 있는가”를 제어하고,
namespace는 “무엇이 보이는가”를 격리한다.
```

---

## 2. cgroup 개념

### 2.1 cgroup이란?

`cgroup`은 `control group`의 약자입니다.

Linux에서 process들을 그룹으로 묶고, 그 그룹 단위로 resource를 계측하거나 제한하는 kernel 기능입니다.

대표적으로 다음 resource를 제어할 수 있습니다.

```text
cpu
memory
io
pids
cpuset
hugetlb
rdma
```

예를 들어 container에 다음과 같은 Kubernetes resource limit을 준다고 해봅시다.

```yaml
resources:
  requests:
    cpu: "500m"
    memory: "256Mi"
  limits:
    cpu: "1"
    memory: "512Mi"
```

kubelet과 container runtime은 이 값을 바탕으로 해당 container process를 특정 cgroup에 넣고, cgroup의 `cpu.max`, `cpu.weight`, `memory.max` 같은 interface file에 값을 설정합니다.

---

### 2.2 cgroup과 Linux process tree는 다르다

Linux process도 계층 구조를 가집니다.

```text
systemd
├─ sshd
│  └─ bash
│     └─ vim
└─ containerd
   └─ containerd-shim
      └─ nginx
```

이 process tree는 **누가 누구를 생성했는가**를 나타냅니다.

반면 cgroup tree는 **어떤 resource control 정책 아래에 있는가**를 나타냅니다.

```text
/sys/fs/cgroup
├─ system.slice
├─ user.slice
└─ kubepods.slice
   ├─ kubepods-burstable.slice
   └─ kubepods-besteffort.slice
```

즉 같은 process를 두 가지 관점에서 볼 수 있습니다.

```text
process tree에서의 위치 = 누가 실행했는가
cgroup tree에서의 위치 = 어떤 resource 정책을 받는가
```

### 2.3 process는 cgroup 사이를 이동할 수 있다

cgroup v2에서는 특정 process를 다른 cgroup으로 이동하려면 대상 cgroup의 `cgroup.procs`에 PID를 씁니다.

```bash
echo <PID> > /sys/fs/cgroup/demo/cgroup.procs
```

이것은 process의 parent를 바꾸는 것이 아닙니다. process tree의 부모-자식 관계는 그대로 두고, resource control group만 바꾸는 것입니다.

---

## 3. cgroup v1과 v2 차이

### 3.1 cgroup v1

cgroup v1에서는 controller별 hierarchy가 따로 존재할 수 있었습니다.

예를 들어 memory controller는 다음과 같은 경로를 사용했습니다.

```bash
mkdir -p /sys/fs/cgroup/memory/foo
echo 50000000 > /sys/fs/cgroup/memory/foo/memory.limit_in_bytes
echo <PID> > /sys/fs/cgroup/memory/foo/cgroup.procs
```

구조는 대략 다음과 같습니다.

```text
/sys/fs/cgroup/
├─ memory/
│  └─ foo/
│     └─ memory.limit_in_bytes
├─ cpu/
├─ pids/
└─ blkio/
```

이 모델에서는 resource 종류별로 process가 서로 다른 cgroup hierarchy에 속할 수 있었습니다.

```text
CPU 기준으로는 /cpu/group-a
Memory 기준으로는 /memory/group-b
```

### 3.2 cgroup v2

cgroup v2는 unified hierarchy입니다. controller별 directory를 따로 두지 않고, 하나의 cgroup tree 안에 controller file들이 함께 존재합니다.

```text
/sys/fs/cgroup/
├─ cgroup.controllers
├─ cgroup.subtree_control
├─ cgroup.procs
├─ cpu.max
├─ cpu.weight
├─ memory.max
├─ memory.current
├─ pids.max
└─ io.max
```

v1의 다음 파일은:

```text
/sys/fs/cgroup/memory/foo/memory.limit_in_bytes
```

v2에서는 다음과 같이 대응됩니다.

```text
/sys/fs/cgroup/foo/memory.max
```

현재 환경이 cgroup v2인지 확인하려면 다음을 실행합니다.

```bash
stat -fc %T /sys/fs/cgroup
```

결과가 다음과 같으면 cgroup v2입니다.

```text
cgroup2fs
```

또는 `/sys/fs/cgroup` 아래에 `cgroup.controllers`, `memory.max`, `cpu.max`가 보이면 cgroup v2일 가능성이 높습니다.

---

## 4. container 안에서 보이는 `/sys/fs/cgroup`

container 안에서 다음을 실행하면:

```bash
cat /proc/self/cgroup
```

cgroup v2 환경에서는 다음처럼 보일 수 있습니다.

```text
0::/
```

이것은 “host 전체의 root cgroup에 있다”는 뜻이 아닙니다.

container는 cgroup namespace에 의해 자신이 속한 cgroup subtree를 `/`처럼 볼 수 있습니다.

```text
host 기준 실제 cgroup path:
/sys/fs/cgroup/system.slice/docker-<container-id>.scope

container 내부에서 보이는 path:
/
```

즉 container 안의 `/sys/fs/cgroup`은 완전히 가짜는 아닙니다. 실제 kernel cgroup interface입니다. 하지만 host 전체의 cgroup tree가 아니라, container에 격리되어 노출된 cgroup view입니다.

또 일반 container에서는 `/sys/fs/cgroup`이 read-only로 mount되는 경우가 많습니다.

```bash
cat /proc/mounts | grep cgroup
```

예시:

```text
cgroup2 /sys/fs/cgroup cgroup2 ro,...
```

이 경우 root 사용자여도 container 안에서 새 cgroup을 만들거나 cgroup 설정을 바꿀 수 없습니다.

```bash
mkdir /sys/fs/cgroup/demo
# mkdir: cannot create directory ... Read-only file system
```

이것은 container가 자기 자신이나 하위 process의 resource policy를 임의로 조작하지 못하게 하기 위한 격리입니다.

---

## 5. cgroup v2 core interface file

cgroup v2에서 `cgroup.*` 파일들은 특정 resource controller가 아니라, cgroup 자체를 관리하거나 상태를 확인하는 core interface입니다.

| 파일                     | 역할                                                          |
| ------------------------ | ------------------------------------------------------------- |
| `cgroup.controllers`     | 현재 cgroup에서 child cgroup에게 넘길 수 있는 controller 목록 |
| `cgroup.subtree_control` | child cgroup에게 활성화할 controller 설정                     |
| `cgroup.procs`           | 현재 cgroup에 속한 process 목록, process 이동에 사용          |
| `cgroup.threads`         | 현재 cgroup에 속한 thread 목록                                |
| `cgroup.events`          | `populated`, `frozen` 같은 cgroup 상태                        |
| `cgroup.freeze`          | cgroup 단위 실행 정지/재개                                    |
| `cgroup.kill`            | cgroup subtree 내 process 종료                                |
| `cgroup.type`            | domain/threaded 등 cgroup type                                |
| `cgroup.stat`            | descendant cgroup 통계                                        |
| `cgroup.max.depth`       | 하위 cgroup 최대 깊이 제한                                    |
| `cgroup.max.descendants` | 하위 cgroup 최대 개수 제한                                    |
| `cgroup.pressure`        | cgroup 단위 PSI accounting 제어                               |

### 5.1 `cgroup.controllers`

현재 cgroup에서 사용할 수 있고, child cgroup에게 넘길 수 있는 controller 목록입니다.

```bash
cat /sys/fs/cgroup/cgroup.controllers
```

예시:

```text
cpuset cpu io memory hugetlb pids rdma
```

### 5.2 `cgroup.subtree_control`

현재 cgroup의 child cgroup에게 어떤 controller를 활성화할지 설정합니다.

```bash
cat /sys/fs/cgroup/cgroup.subtree_control
```

예시:

```text
cpuset cpu io memory hugetlb pids rdma
```

중요한 점은 다음입니다.

```text
cgroup.subtree_control은 현재 cgroup 자기 자신에게 controller를 적용하는 파일이 아니다.
child cgroup에게 어떤 controller를 열어줄지 결정하는 파일이다.
```

예를 들어 parent에서 `cpu` controller를 끄면:

```bash
echo "-cpu" > /sys/fs/cgroup/cgroup.subtree_control
```

child cgroup의 `cgroup.controllers`에서 `cpu`가 사라질 수 있습니다.

```bash
cat /sys/fs/cgroup/demo/cgroup.controllers
```

다시 켜려면:

```bash
echo "+cpu" > /sys/fs/cgroup/cgroup.subtree_control
```

관계를 그림으로 표현하면 다음과 같습니다.

```text
/sys/fs/cgroup
├─ cgroup.subtree_control  # child에게 넘겨줄 controller 설정
└─ demo
   └─ cgroup.controllers   # parent가 넘겨준 controller 목록
```

### 5.3 `cgroup.procs`

현재 cgroup에 속한 process 목록입니다.

```bash
cat /sys/fs/cgroup/demo/cgroup.procs
```

PID를 쓰면 해당 process를 cgroup으로 이동시킵니다.

```bash
echo <PID> > /sys/fs/cgroup/demo/cgroup.procs
```

터미널 세션 자체를 cgroup에 넣을 수도 있습니다.

```bash
echo $$ > /sys/fs/cgroup/demo/cgroup.procs
```

그 후 해당 shell에서 실행한 child process는 보통 같은 cgroup을 상속합니다.

확인:

```bash
cat /proc/$$/cgroup
```

### 5.4 `cgroup.events`

cgroup의 주요 상태를 보여줍니다.

```bash
cat /sys/fs/cgroup/demo/cgroup.events
```

예시:

```text
populated 1
frozen 0
```

`populated`는 현재 cgroup 또는 descendant cgroup 안에 live process가 있는지를 나타냅니다.

```text
populated 1 = 이 cgroup subtree 안에 살아 있는 process가 있음
populated 0 = 이 cgroup subtree 안에 살아 있는 process가 없음
```

Kubernetes/container runtime 관점에서는 container process가 종료되면 해당 cgroup subtree의 `populated`가 `0`이 될 수 있습니다. 이는 runtime이나 systemd가 cgroup을 정리할 수 있는 상태를 알려주는 신호로 활용될 수 있습니다.

단, `cgroup.events`가 resource를 직접 회수하는 것은 아닙니다.

```text
process 종료 → 메모리, fd 등 process resource 해제
runtime/systemd cleanup → 비어 있는 cgroup directory 제거
cgroup.events → 상태 변화 관찰용 interface
```

`frozen`은 해당 cgroup이 freeze 상태인지 나타냅니다.

```text
frozen 0 = freeze 완료 상태가 아님
frozen 1 = cgroup이 freeze된 상태
```

### 5.5 `cgroup.freeze`

cgroup 단위로 task 실행을 일시정지하거나 재개합니다.

```bash
echo 1 > /sys/fs/cgroup/demo/cgroup.freeze  # freeze
echo 0 > /sys/fs/cgroup/demo/cgroup.freeze  # thaw/resume
```

freeze는 CPU limit과 다릅니다.

```text
cpu.max        = 실행은 시키되 CPU time 상한을 둠
cpu.weight     = CPU 경쟁 시 상대적 비율 조정
cgroup.freeze  = cgroup 안의 task 실행 자체를 멈춤
```

frozen 상태의 container는 application code를 실행하지 못합니다. 다만 이미 점유한 memory나 열린 socket, kernel object 상태는 유지될 수 있습니다.

따라서 freeze는 resource scheduling보다는 lifecycle, debugging, checkpoint/restore 계열의 제어 기능에 가깝습니다.

---

## 6. CPU controller

### 6.1 `cpu.weight`

`cpu.weight`는 sibling cgroup 사이에서 CPU가 부족할 때 CPU time을 어떤 비율로 나눌지 정하는 상대적 가중치입니다.

```bash
cat /sys/fs/cgroup/A/cpu.weight
cat /sys/fs/cgroup/B/cpu.weight
```

설정 예시:

```bash
echo 100 > /sys/fs/cgroup/A/cpu.weight
echo 200 > /sys/fs/cgroup/B/cpu.weight
```

이 경우 A와 B가 같은 parent 아래에서 CPU를 두고 경쟁하면 대략 다음 비율이 됩니다.

```text
A : B = 100 : 200 = 1 : 2
```

중요한 점은 `cpu.weight`가 hard limit이 아니라는 것입니다.

```text
CPU가 남아 있으면 weight가 낮아도 필요한 만큼 CPU를 쓸 수 있다.
CPU가 부족해서 sibling cgroup끼리 경쟁할 때만 weight 차이가 의미 있게 나타난다.
```

예를 들어 VM에 4 vCPU가 있고 A/B 각각에서 `stress-ng --cpu 1`만 실행하면 두 process가 각각 100% CPU를 사용할 수 있습니다. 전체 CPU 사용률은 약 50%이고 나머지 CPU는 idle일 수 있습니다.

이것은 이상한 것이 아니라 정상입니다.

### 6.2 `cpu.weight` 데모

A/B cgroup 생성:

```bash
sudo -i
cd /sys/fs/cgroup

# child cgroup에서 cpu controller를 사용할 수 있게 함
echo +cpu > cgroup.subtree_control

mkdir A B
echo 100 > A/cpu.weight
echo 200 > B/cpu.weight
```

터미널 1:

```bash
sudo -i
echo $$ > /sys/fs/cgroup/A/cgroup.procs
cat /proc/$$/cgroup
```

터미널 2:

```bash
sudo -i
echo $$ > /sys/fs/cgroup/B/cgroup.procs
cat /proc/$$/cgroup
```

CPU 경쟁을 확실히 만들려면 두 터미널에서 같은 CPU core에 고정해서 실행합니다.

터미널 1:

```bash
taskset -c 0 stress-ng --cpu 1
```

터미널 2:

```bash
taskset -c 0 stress-ng --cpu 1
```

`top` 또는 `htop`에서 보면 A 쪽 worker가 약 33%, B 쪽 worker가 약 66%에 가까운 CPU time을 얻는 것을 기대할 수 있습니다.

더 정확히는 `cpu.stat`의 `usage_usec` 증가량을 비교합니다.

```bash
cat /sys/fs/cgroup/A/cpu.stat | grep usage_usec
cat /sys/fs/cgroup/B/cpu.stat | grep usage_usec
```

### 6.3 `cpu.max`

`cpu.max`는 hard quota입니다.

형식은 다음과 같습니다.

```text
<quota> <period>
```

단위는 microseconds입니다.

예시:

```bash
echo "50000 100000" > /sys/fs/cgroup/A/cpu.max
```

의미:

```text
100ms period마다 최대 50ms만 CPU 사용 가능
대략 0.5 CPU limit
```

제한 없음은 다음처럼 표현됩니다.

```text
max 100000
```

`cpu.weight`와 비교하면 다음과 같습니다.

| 파일         | 성격        | 의미                                        |
| ------------ | ----------- | ------------------------------------------- |
| `cpu.weight` | 상대적 비율 | CPU 경쟁 시 sibling cgroup 사이의 배분 비율 |
| `cpu.max`    | 절대 상한   | CPU가 남아도 quota 이상 사용 불가           |

### 6.4 `cpu.stat`

CPU 사용량과 throttling 통계를 보여줍니다.

```bash
cat /sys/fs/cgroup/A/cpu.stat
```

예시 필드:

```text
usage_usec
user_usec
system_usec
nr_periods
nr_throttled
throttled_usec
```

`usage_usec` 증가량을 시간 간격으로 나누면 해당 cgroup의 CPU 사용량을 계산할 수 있습니다.

`cpu.max`에 의해 throttling이 발생하면 `nr_throttled`, `throttled_usec`가 증가합니다.

---

## 7. Memory controller

cgroup v2에서 memory hard limit은 `memory.max`로 설정합니다.

```bash
echo 50000000 > /sys/fs/cgroup/demo/memory.max
```

현재 memory 사용량은 다음으로 확인합니다.

```bash
cat /sys/fs/cgroup/demo/memory.current
```

주요 파일:

| 파일              | 역할                           |
| ----------------- | ------------------------------ |
| `memory.max`      | hard memory limit              |
| `memory.current`  | 현재 memory 사용량             |
| `memory.high`     | soft pressure limit 성격       |
| `memory.low`      | best-effort memory protection  |
| `memory.min`      | stronger memory protection     |
| `memory.events`   | OOM, high, max 등 memory event |
| `memory.stat`     | memory accounting 상세 통계    |
| `memory.pressure` | memory PSI                     |

Kubernetes의 container memory limit은 cgroup v2 기준으로 대략 `memory.max`와 연결됩니다.

---

## 8. Kubernetes와 cgroup

Kubernetes에서 Pod/Container resource request/limit은 kubelet과 container runtime을 통해 cgroup 설정으로 반영됩니다.

```text
Kubernetes Pod Spec
→ kubelet
→ CRI(containerd/CRI-O)
→ OCI runtime(runc 등)
→ Linux cgroup
```

대표 연결은 다음과 같습니다.

| Kubernetes 설정           | cgroup v2 interface | 설명                         |
| ------------------------- | ------------------- | ---------------------------- |
| `resources.requests.cpu`  | `cpu.weight`        | CPU 경쟁 시 상대적 weight    |
| `resources.limits.cpu`    | `cpu.max`           | CPU hard quota               |
| `resources.limits.memory` | `memory.max`        | memory hard limit            |
| Pod/Container process     | `cgroup.procs`      | process가 특정 cgroup에 소속 |

Kubernetes QoS class도 cgroup과 밀접하게 연결됩니다.

```text
Guaranteed
Burstable
BestEffort
```

노드 memory pressure 상황에서 kubelet은 Pod의 request/usage/QoS 등을 고려해 eviction 대상을 결정합니다. cgroup은 이때 resource usage를 측정하고 limit을 강제하는 기반 역할을 합니다.

---

## 9. namespace 개념

### 9.1 namespace란?

Linux namespace는 process가 바라보는 kernel resource view를 격리하는 기능입니다.

container 안에서 `ps`, `hostname`, `ip addr`, `mount`, `/proc/self/cgroup` 결과가 host와 다르게 보이는 이유가 namespace입니다.

namespace는 새로운 kernel을 만드는 것이 아닙니다. host kernel은 공유하되, process마다 보이는 view를 다르게 만드는 것입니다.

---

### 9.2 주요 namespace

| Namespace         | 격리 대상                     | container에서의 의미                          |
| ----------------- | ----------------------------- | --------------------------------------------- |
| PID namespace     | PID view                      | container 안에서 PID 1을 가질 수 있음         |
| Mount namespace   | mount table/filesystem view   | container rootfs가 `/`처럼 보임               |
| Network namespace | network stack                 | interface, IP, route, port table 분리         |
| UTS namespace     | hostname/domainname           | container별 hostname 가능                     |
| IPC namespace     | SysV IPC, POSIX message queue | IPC object 격리                               |
| User namespace    | UID/GID mapping               | container root와 host root를 다르게 매핑 가능 |
| Cgroup namespace  | cgroup path view              | `/proc/self/cgroup`이 `/`처럼 보일 수 있음    |
| Time namespace    | clock offset 일부             | monotonic/boottime clock offset 격리          |

---

## 10. PID namespace

PID namespace는 process ID 공간을 격리합니다.

Host에서 보면 container process는 일반 PID를 가진 process입니다.

```text
Host view
PID 2450 nginx
PID 2451 worker
```

Container 안에서는 다르게 보일 수 있습니다.

```text
Container view
PID 1 nginx
PID 2 worker
```

PID namespace는 계층적입니다.

```text
parent namespace는 child namespace의 process를 볼 수 있다.
child namespace는 parent namespace의 process를 볼 수 없다.
```

### PID 1의 의미

container entrypoint process는 보통 container 안에서 PID 1이 됩니다.

Linux에서 PID 1은 signal handling과 orphan/zombie process 처리에서 특수합니다. 그래서 container에서는 `--init`, `tini`, `dumb-init` 같은 작은 init process를 사용하는 경우도 있습니다.

---

## 11. Mount namespace와 rootfs

Mount namespace는 process가 보는 mount table을 격리합니다.

container runtime은 container image로부터 root filesystem을 준비하고, 새 mount namespace 안에서 process가 보는 `/`를 그 rootfs로 바꿉니다.

```text
변경 전:
process의 / → host root filesystem

변경 후:
process의 / → container image rootfs
```

이것이 “root filesystem을 container rootfs로 변경한다”는 의미입니다.

### chroot와 pivot_root

개념적으로는 `chroot`를 떠올리면 쉽습니다.

```bash
chroot /some/rootfs /bin/bash
```

이후 process 입장에서는 다음처럼 보입니다.

```text
/some/rootfs/bin → /bin
/some/rootfs/etc → /etc
```

container runtime은 단순 `chroot`보다 더 정교하게 `pivot_root` 또는 유사 절차를 사용해 root mount 자체를 교체합니다.

대략적인 흐름은 다음과 같습니다.

```text
1. 새 mount namespace 생성
2. container rootfs 준비
3. rootfs를 mount point로 구성
4. pivot_root로 새 rootfs를 `/`로 전환
5. old root unmount
6. /proc, /sys, /dev 등을 container용으로 mount
7. app process exec
```

---

## 12. `/proc`, `/sys`, `/dev` pseudo filesystem

`/proc`, `/sys`, `/dev`는 일반적인 디스크 파일이 아니라 kernel interface를 파일처럼 노출하는 pseudo filesystem입니다.

### `/proc`

process와 kernel 정보를 제공합니다.

```bash
cat /proc/cpuinfo
cat /proc/meminfo
cat /proc/self/status
ls /proc
```

`ps` 같은 도구는 `/proc`를 읽어서 process 정보를 보여줍니다. 새 PID namespace를 만들었다면 `/proc`도 새 namespace 기준으로 다시 mount해야 `ps`가 올바르게 보입니다.

### `/sys`

kernel object, device, driver, cgroup 정보를 노출합니다.

```bash
ls /sys/class/net
ls /sys/fs/cgroup
ls /sys/block
```

container 안의 `/sys`는 보통 제한적으로 mount됩니다. 특히 `/sys/fs/cgroup`은 read-only로 보이는 경우가 많습니다.

### `/dev`

device file을 제공합니다.

```text
/dev/null
/dev/zero
/dev/random
/dev/urandom
/dev/tty
/dev/pts
/dev/shm
```

container runtime은 host의 모든 device를 노출하지 않고, container 실행에 필요한 최소 device만 구성합니다.

### 왜 다시 mount해야 하는가?

container rootfs 안에 `/proc`, `/sys`, `/dev`라는 directory가 있어도, 그 자체로는 그냥 directory일 뿐입니다.

새 mount namespace 안에서 procfs/sysfs/tmpfs/devpts 등을 mount해야 실제 kernel interface로 동작합니다.

```text
mount proc  → /proc
mount sysfs → /sys
mount tmpfs/devtmpfs → /dev
mount devpts → /dev/pts
mount tmpfs → /dev/shm
```

---

## 13. Network namespace

Network namespace는 network stack을 격리합니다.

격리되는 대표 요소는 다음과 같습니다.

```text
network interface
IP address
routing table
ARP table
port binding space
/proc/net view
```

Docker bridge network를 단순화하면 다음과 같습니다.

```text
container eth0 <---- veth pair ----> host veth ----> docker0 bridge
```

Kubernetes에서는 Pod 단위로 network namespace를 공유합니다.

```text
Pod
├─ app container
└─ sidecar container

두 container는 같은 network namespace를 공유하므로 localhost 통신 가능
```

즉 Pod IP는 container 개별 IP가 아니라 Pod network namespace의 IP입니다.

---

## 14. UTS, IPC, User, Cgroup namespace

### UTS namespace

hostname/domainname을 격리합니다.

```bash
hostname
```

container 안 hostname을 바꿔도 host hostname은 바뀌지 않습니다.

### IPC namespace

System V shared memory, semaphore, message queue, POSIX message queue 같은 IPC object를 격리합니다.

Kubernetes에서는 `hostIPC: true`를 사용하면 host IPC namespace를 공유할 수 있습니다.

### User namespace

UID/GID mapping을 격리합니다.

```text
container view: uid 0 root
host view: uid 100000
```

이렇게 mapping하면 container 안 root가 host root와 같지 않게 됩니다. rootless container의 중요한 기반입니다.

### Cgroup namespace

process가 보는 cgroup path view를 격리합니다.

container 안에서:

```bash
cat /proc/self/cgroup
```

결과가 다음처럼 나올 수 있습니다.

```text
0::/
```

host 기준 실제 cgroup path는 더 깊은 위치일 수 있습니다.

---

## 15. namespace 관련 syscall

namespace 관련 핵심 syscall은 다음 세 가지입니다.

```text
clone()   = 새 process를 만들면서 새 namespace도 함께 생성 가능
unshare() = 현재 process를 새 namespace로 분리
setns()   = 이미 존재하는 namespace에 진입
```

### 15.1 `clone()`

새 process를 만들면서 namespace 생성 flag를 전달할 수 있습니다.

개념 예시:

```c
clone(child_func, child_stack,
      CLONE_NEWPID |
      CLONE_NEWNS  |
      CLONE_NEWNET |
      CLONE_NEWUTS |
      CLONE_NEWIPC |
      SIGCHLD,
      NULL);
```

주요 flag:

```text
CLONE_NEWPID     새 PID namespace
CLONE_NEWNS      새 mount namespace
CLONE_NEWNET     새 network namespace
CLONE_NEWUTS     새 UTS namespace
CLONE_NEWIPC     새 IPC namespace
CLONE_NEWUSER    새 user namespace
CLONE_NEWCGROUP  새 cgroup namespace
CLONE_NEWTIME    새 time namespace
```

### 15.2 `unshare()`

현재 process를 새 namespace로 분리합니다. CLI 명령으로는 `unshare`를 사용합니다.

```bash
sudo unshare --uts bash
```

### 15.3 `setns()`

이미 존재하는 namespace에 진입합니다. CLI 명령으로는 `nsenter`를 사용합니다.

```bash
sudo nsenter --target <PID> --net bash
```

---

## 16. namespace 핸즈온

> 아래 실습은 Docker container 내부보다 VM 또는 일반 Linux host에서 수행하는 것을 권장합니다. container 내부에서는 namespace 생성 권한이 제한될 수 있습니다.

필요 도구:

```bash
sudo apt update
sudo apt install -y util-linux procps iproute2 stress-ng
```

---

### Demo 1. namespace inode 확인

현재 shell의 namespace를 확인합니다.

```bash
ls -l /proc/$$/ns
```

예시:

```text
cgroup -> cgroup:[4026531835]
ipc    -> ipc:[4026531839]
mnt    -> mnt:[4026531841]
net    -> net:[4026531840]
pid    -> pid:[4026531836]
user   -> user:[4026531837]
uts    -> uts:[4026531838]
```

대괄호 안 숫자는 namespace inode입니다. 두 process의 namespace inode가 같으면 같은 namespace를 공유하고, 다르면 다른 namespace입니다.

---

### Demo 2. UTS namespace

터미널 1:

```bash
hostname
sudo unshare --uts bash
```

새 shell 안에서:

```bash
hostname
hostname demo-uts
hostname
```

터미널 2에서 host hostname 확인:

```bash
hostname
```

결과적으로 namespace 안 hostname만 바뀌고 host hostname은 유지됩니다.

---

### Demo 3. PID namespace

```bash
sudo unshare --pid --fork --mount-proc bash
```

새 shell 안에서:

```bash
echo $$
ps -ef
```

예상:

```text
UID   PID  PPID  CMD
root    1     0  bash
root    2     1  ps -ef
```

중요한 옵션:

```text
--pid         새 PID namespace 생성
--fork        새 PID namespace 안에서 child process 실행
--mount-proc  새 PID namespace 기준으로 /proc mount
```

`--mount-proc`가 없으면 `ps`가 host 기준 `/proc`를 보고 혼란스러운 결과를 낼 수 있습니다.

---

### Demo 4. Mount namespace

```bash
sudo unshare --mount bash
```

새 shell 안에서:

```bash
mount --make-rprivate /
mkdir -p /tmp/ns-demo
mount -t tmpfs tmpfs /tmp/ns-demo
mount | grep ns-demo
```

다른 터미널에서 host mount table 확인:

```bash
mount | grep ns-demo
```

host에서는 보이지 않는 것이 정상입니다. 즉 mount namespace 안에서 발생한 mount 변경이 host mount namespace로 전파되지 않습니다.

---

### Demo 5. Network namespace

```bash
sudo unshare --net bash
```

새 shell 안에서:

```bash
ip addr
ip route
```

보통 `lo`만 보이고 host의 `eth0`, `ens*`, `docker0` 등은 보이지 않습니다.

loopback을 올려봅니다.

```bash
ip link set lo up
ip addr
```

이 데모는 network interface와 routing table이 namespace 단위로 격리된다는 것을 보여줍니다.

---

### Demo 6. User namespace

환경에 따라 user namespace 생성이 제한될 수 있습니다.

```bash
unshare --user --map-root-user bash
```

새 shell 안에서:

```bash
id
cat /proc/self/uid_map
cat /proc/self/gid_map
```

예시:

```text
uid=0(root) gid=0(root)
         0       1000          1
```

이는 namespace 안 UID 0이 host UID 1000에 매핑되었음을 의미합니다.

---

### Demo 7. nsenter로 기존 namespace에 진입

터미널 1:

```bash
sudo unshare --uts --pid --fork --mount-proc bash
hostname demo-ns
sleep 10000
```

터미널 2에서 host 기준 PID 확인:

```bash
ps -ef | grep sleep
```

예를 들어 PID가 `12345`라면:

```bash
sudo nsenter --target 12345 --uts bash
hostname
```

결과:

```text
demo-ns
```

즉 `nsenter`는 이미 존재하는 namespace에 들어가는 도구입니다.

PID namespace와 mount namespace까지 함께 들어가려면 다음처럼 실행합니다.

```bash
sudo nsenter --target 12345 --pid --mount --uts bash
ps -ef
```

---

## 17. rootfs 변경 핸즈온

이 실습은 “container image rootfs를 `/`처럼 보이게 한다”는 감각을 이해하기 위한 간단한 데모입니다.

### 17.1 rootfs 준비

```bash
sudo apt update
sudo apt install -y debootstrap

sudo mkdir -p /tmp/rootfs
sudo debootstrap --variant=minbase jammy /tmp/rootfs http://archive.ubuntu.com/ubuntu/
```

### 17.2 새 namespace에서 chroot

```bash
sudo unshare --mount --uts --pid --fork bash
```

새 shell 안에서:

```bash
mount --make-rprivate /

mount -t proc proc /tmp/rootfs/proc
mount --rbind /sys /tmp/rootfs/sys
mount --rbind /dev /tmp/rootfs/dev

chroot /tmp/rootfs /bin/bash
```

chroot 안에서:

```bash
cat /etc/os-release
ps -ef
hostname
```

이 실습은 완전한 container는 아닙니다. network namespace, cgroup, capability, seccomp, overlayfs, pivot_root 등이 빠져 있습니다.

하지만 다음 개념을 보여주기에는 충분합니다.

```text
process가 보는 `/`는 바꿀 수 있다.
/proc, /sys, /dev는 rootfs 안의 일반 directory가 아니라 별도 mount가 필요한 kernel interface다.
```

---

## 18. Docker/Kubernetes와 namespace

Docker/containerd/runc는 사람이 직접 수행한 namespace/cgroup/rootfs 작업을 자동화합니다.

단순화하면 container 생성 흐름은 다음과 같습니다.

```text
1. image layer를 가져옴
2. overlayfs로 container rootfs 구성
3. clone/unshare 계열 기능으로 namespace 생성
   - mount
   - pid
   - net
   - uts
   - ipc
   - cgroup
   - user 선택적
4. cgroup 생성 및 resource limit 설정
5. mount namespace 안에서 rootfs를 `/`로 전환
6. /proc, /sys, /dev mount
7. capability/seccomp/AppArmor/SELinux 등 적용
8. container entrypoint exec
```

Kubernetes에서는 Pod 단위 namespace 공유가 중요합니다.

```text
Pod
├─ shared network namespace
│  ├─ Pod IP
│  ├─ route table
│  └─ localhost
├─ container A
│  ├─ mount namespace
│  ├─ pid namespace
│  └─ cgroup
└─ container B
   ├─ mount namespace
   ├─ pid namespace
   └─ cgroup
```

같은 Pod 안의 container들이 `localhost`로 통신할 수 있는 이유는 같은 network namespace를 공유하기 때문입니다.

PID namespace는 기본적으로 container별로 분리되지만, Kubernetes에서 다음 옵션을 사용하면 Pod 내 container들이 process namespace를 공유할 수 있습니다.

```yaml
shareProcessNamespace: true
```

---

## 19. 핵심 요약

```text
cgroup
- Linux process group의 resource usage를 계측하고 제한한다.
- cgroup tree는 process tree와 다르다.
- cgroup v2는 unified hierarchy를 사용한다.
- cgroup.procs에 PID를 쓰면 process를 cgroup으로 이동시킬 수 있다.
- cpu.weight는 상대적 비율이고, cpu.max는 hard quota다.
- memory.max는 memory hard limit이다.
- Kubernetes request/limit은 kubelet과 runtime을 통해 cgroup 설정으로 연결된다.
```

```text
namespace
- process가 보는 kernel resource view를 격리한다.
- PID namespace는 process ID view를 분리한다.
- Mount namespace는 mount table과 rootfs view를 분리한다.
- Network namespace는 interface, IP, route, port space를 분리한다.
- UTS namespace는 hostname을 분리한다.
- User namespace는 UID/GID mapping을 분리한다.
- Cgroup namespace는 cgroup path view를 분리한다.
```

```text
container
= host kernel 위의 process
+ namespace로 격리된 view
+ cgroup으로 제한된 resource
+ container rootfs
+ 보안 제한
```

이 관점으로 보면 Docker, containerd, runc, kubelet, Kubernetes Pod resource limit, Pod network, sidecar 구조를 더 낮은 수준에서 이해할 수 있습니다.
