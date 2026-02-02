# PostgreSQL 비동기/동기 연결 문자열 구분

## 개요

SQLAlchemy와 FastAPI를 사용하는 비동기 애플리케이션에서 PostgreSQL 데이터베이스에 연결할 때, 두 가지 종류의 연결 문자열이 필요합니다. 하나는 애플리케이션 런타임용이고, 다른 하나는 데이터베이스 마이그레이션 도구(Alembic)용입니다. 이 문서에서는 왜 두 개의 연결 문자열이 필요한지, 각각의 역할과 차이점에 대해 상세히 설명합니다.

## 배경: 같은 데이터베이스, 다른 접근 방식

두 연결 문자열 모두 동일한 PostgreSQL 인스턴스를 가리킵니다. `.env` 파일에 정의된 `host`, `port`, `database`, `user`, `password` 값을 조합하여 데이터베이스 접속 URL을 생성하는 역할을 합니다. 그러나 이 두 문자열이 사용되는 맥락과 목적이 완전히 다르기 때문에, 서로 다른 드라이버와 프로토콜을 사용해야 합니다.

## 핵심 차이점: 비동기 런타임 vs 동기 마이그레이션

### 애플리케이션 런타임 (비동기)

FastAPI 서버는 `uvicorn`과 같은 ASGI 서버를 통해 실행되며, 이벤트 루프 기반으로 여러 요청을 동시에 효율적으로 처리합니다. 이러한 환경에서 데이터베이스 작업도 비동기 방식으로 처리하면 성능상 큰 이점이 있습니다. 하나의 요청이 데이터베이스 응답을 기다리는 동안 다른 요청을 처리할 수 있기 때문에, 블로킹 없이 높은 처리량을 유지할 수 있습니다.

따라서 애플리케이션 런타임에서는 SQLAlchemy의 비동기 엔진과 `async/await` 구문을 사용하여 데이터베이스와 통신합니다.

### 마이그레이션 도구 (동기)

반면 Alembic은 데이터베이스 스키마를 관리하는 명령줄 도구입니다. 개발자가 터미널에서 직접 실행하는 도구로, 테이블 생성, 컬럼 추가, 인덱스 변경 등의 스키마 변경 작업을 수행합니다.

```bash
alembic revision --autogenerate -m "create user table"
alembic upgrade head
```

Alembic은 이벤트 루프 내에서 실행되지 않으며, 한 번 실행되고 종료되는 일회성 작업입니다. 기본적으로 동기 방식으로 설계되어 있어, 비동기 드라이버를 사용할 수 없습니다. 따라서 Alembic은 전통적인 동기 방식의 데이터베이스 드라이버를 필요로 합니다.

## postgres_connection_string: 비동기 애플리케이션용

```python
@property
def postgres_connection_string(self) -> str:
    """Build PostgreSQL connection string for SQLAlchemy."""
    password = self.postgres_password.get_secret_value() if self.postgres_password else ""
    return (
        f"postgresql+asyncpg://{self.postgres_user}:{password}"
        f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"
    )
```

### 목적

FastAPI 애플리케이션에서 SQLAlchemy의 비동기 엔진을 사용하기 위한 연결 문자열입니다.

### 사용 드라이버: asyncpg

`postgresql+asyncpg://`라는 프로토콜 지정자에서 알 수 있듯이, 이 연결 문자열은 `asyncpg` 드라이버를 사용합니다. `asyncpg`는 PostgreSQL 전용 비동기 드라이버로, 순수 파이썬으로 작성되었으며 매우 빠른 성능을 자랑합니다.

SQLAlchemy는 연결 문자열의 `+asyncpg` 부분을 보고, 비동기 드라이버를 사용해야 한다는 것을 인식합니다. 이를 통해 SQLAlchemy는 내부적으로 비동기 작업을 처리할 수 있는 `AsyncEngine`과 `AsyncSession`을 생성합니다.

### 사용 예시

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

engine = create_async_engine(settings.postgres_connection_string)
async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_user(user_id: int):
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
```

### 특징

- **비동기 처리**: `await` 키워드를 사용하여 논블로킹 방식으로 데이터베이스 작업을 수행합니다.
- **높은 성능**: 이벤트 루프 내에서 여러 요청을 동시에 처리할 수 있어 처리량이 높습니다.
- **FastAPI와의 완벽한 호환**: FastAPI의 비동기 엔드포인트와 자연스럽게 통합됩니다.
- **Alembic과 호환 불가**: Alembic은 동기 방식으로 작동하므로 이 연결 문자열을 사용할 수 없습니다.

## postgres_sync_connection_string: Alembic 마이그레이션용

```python
@property
def postgres_sync_connection_string(self) -> str:
    """Build PostgreSQL connection string for Alembic (sync)."""
    password = self.postgres_password.get_secret_value() if self.postgres_password else ""
    return (
        f"postgresql+psycopg2://{self.postgres_user}:{password}"
        f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"
        f"?sslmode={self.postgres_ssl_mode}"
    )
```

### 목적

Alembic 데이터베이스 마이그레이션 도구에서 사용하기 위한 동기 방식의 연결 문자열입니다.

### 사용 드라이버: psycopg2

`postgresql+psycopg2://`라는 프로토콜 지정자는 `psycopg2` 드라이버를 사용한다는 것을 나타냅니다. `psycopg2`는 PostgreSQL의 가장 널리 사용되는 동기 드라이버로, C 라이브러리인 `libpq`를 기반으로 합니다.

SQLAlchemy는 이 드라이버를 사용하여 전통적인 블로킹 방식으로 데이터베이스와 통신합니다. 이는 Alembic과 같은 CLI 도구에 적합한 방식입니다.

### 사용 예시

Alembic의 `env.py` 파일에서 이 연결 문자열을 설정합니다:

```python
# alembic/env.py
from app.config import settings

config.set_main_option(
    "sqlalchemy.url",
    settings.postgres_sync_connection_string
)
```

### 특징

- **동기 방식**: 블로킹 방식으로 작동하며, `await` 키워드를 사용하지 않습니다.
- **Alembic 전용**: 마이그레이션 스크립트 생성 및 실행에 사용됩니다.
- **SSL 옵션 포함**: `?sslmode={self.postgres_ssl_mode}` 쿼리 파라미터를 통해 SSL 연결 모드를 지정합니다.
- **이벤트 루프 불필요**: 단순한 CLI 명령 실행 환경에서 작동합니다.

## SSL 설정의 차이

두 연결 문자열을 비교하면, SSL 관련 설정에도 차이가 있음을 알 수 있습니다.

### asyncpg (비동기)

`asyncpg`는 SSL 설정을 연결 문자열의 쿼리 파라미터가 아닌, 드라이버 수준에서 SSL 컨텍스트 객체를 통해 처리합니다. 따라서 연결 문자열에 `sslmode` 파라미터가 포함되지 않습니다.

필요한 경우 엔진 생성 시 별도의 `connect_args`를 통해 SSL 옵션을 전달할 수 있습니다:

```python
engine = create_async_engine(
    settings.postgres_connection_string,
    connect_args={"ssl": ssl_context}
)
```

### psycopg2 (동기)

`psycopg2`는 연결 문자열의 쿼리 파라미터로 직접 SSL 모드를 지정합니다. `?sslmode=require`와 같은 형태로 연결 문자열에 포함되며, PostgreSQL 클라이언트가 이해하는 표준 방식입니다.

일반적인 `sslmode` 값:
- `disable`: SSL을 사용하지 않음
- `allow`: 가능하면 SSL 사용
- `prefer`: SSL을 선호하지만 필수는 아님 (기본값)
- `require`: SSL 필수
- `verify-ca`: SSL 필수 및 인증서 검증
- `verify-full`: SSL 필수 및 전체 검증

## 왜 두 개가 필요한가?

이제 핵심 질문에 답할 수 있습니다. 왜 같은 데이터베이스에 접속하는데 두 개의 연결 문자열이 필요한가?

### 실행 모델의 근본적 차이

애플리케이션 런타임과 마이그레이션 도구는 완전히 다른 실행 모델을 가지고 있습니다.

**애플리케이션 런타임**은 이벤트 루프 기반의 비동기 환경에서 실행됩니다. 수많은 동시 요청을 효율적으로 처리하기 위해 논블로킹 I/O가 필수적입니다. 따라서 비동기 드라이버인 `asyncpg`가 필요합니다.

**Alembic**은 단일 작업을 수행하고 종료되는 CLI 도구입니다. 이벤트 루프가 없으며, 비동기 처리의 이점을 얻을 수 없습니다. 오히려 Alembic의 내부 구조는 동기 방식으로 설계되어 있어, 비동기 드라이버를 사용하면 오류가 발생합니다.

### 드라이버 호환성

SQLAlchemy는 매우 유연한 ORM이지만, 비동기와 동기 드라이버는 완전히 다른 API를 제공합니다. `AsyncEngine`은 `asyncpg`와 같은 비동기 드라이버만 사용할 수 있고, 일반 `Engine`은 `psycopg2`와 같은 동기 드라이버만 사용할 수 있습니다.

따라서 애플리케이션과 Alembic이 같은 데이터베이스를 사용하더라도, 각자의 실행 모델에 맞는 드라이버와 연결 문자열을 사용해야 합니다.

## 잘못된 연결 문자열 사용 시 발생하는 문제

### Alembic에 asyncpg URL을 사용하는 경우

만약 Alembic 설정에 `postgresql+asyncpg://`로 시작하는 비동기 연결 문자열을 사용하면 다음과 같은 오류가 발생합니다:

```
sqlalchemy.exc.NoSuchModuleError: Can't load plugin: sqlalchemy.dialects:postgresql.asyncpg
```

또는:

```
RuntimeError: Event loop is closed
```

Alembic은 동기 방식으로 작동하기 때문에 비동기 드라이버를 로드하거나 사용할 수 없습니다. 이 오류를 처음 접하면 원인을 파악하는 데 상당한 시간이 소요될 수 있습니다.

### 애플리케이션에 psycopg2 URL을 사용하는 경우

반대로 FastAPI 애플리케이션에서 `postgresql+psycopg2://`로 시작하는 동기 연결 문자열을 사용하면, `create_async_engine()`이 오류를 발생시키거나, 비동기 세션에서 `await`를 사용할 수 없게 됩니다.

최악의 경우, 애플리케이션이 실행되더라도 모든 데이터베이스 작업이 블로킹 방식으로 처리되어 성능이 크게 저하됩니다.

## 실전 예시: 전체 구조

### 설정 클래스

```python
from pydantic import SecretStr
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    postgres_host: str
    postgres_port: int
    postgres_database: str
    postgres_user: str
    postgres_password: SecretStr
    postgres_ssl_mode: str

    @property
    def postgres_connection_string(self) -> str:
        """FastAPI + SQLAlchemy Async용"""
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"
        )

    @property
    def postgres_sync_connection_string(self) -> str:
        """Alembic 마이그레이션용"""
        password = self.postgres_password.get_secret_value()
        return (
            f"postgresql+psycopg2://{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_database}"
            f"?sslmode={self.postgres_ssl_mode}"
        )

settings = Settings()
```

### 애플리케이션에서 사용

```python
# database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

engine = create_async_engine(
    settings.postgres_connection_string,
    echo=True,
    future=True
)

async_session = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

# FastAPI 엔드포인트
from fastapi import Depends

async def get_db():
    async with async_session() as session:
        yield session

@app.get("/users/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    return user
```

### Alembic에서 사용

```python
# alembic/env.py
from app.config import settings

def run_migrations_online():
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = settings.postgres_sync_connection_string
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()
```

## 모범 사례

### 1. 환경 변수 분리

`.env` 파일에서 공통 설정을 관리하되, 연결 문자열 생성은 설정 클래스에서 처리합니다:

```bash
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DATABASE=mydb
POSTGRES_USER=myuser
POSTGRES_PASSWORD=mypassword
POSTGRES_SSL_MODE=require
```

### 2. 비밀번호 보안

`pydantic`의 `SecretStr`을 사용하여 비밀번호가 로그에 출력되지 않도록 보호합니다:

```python
postgres_password: SecretStr

# 사용 시
password = self.postgres_password.get_secret_value()
```

### 3. 연결 풀 설정

프로덕션 환경에서는 적절한 연결 풀 설정이 중요합니다:

```python
engine = create_async_engine(
    settings.postgres_connection_string,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,  # 연결 유효성 검사
    pool_recycle=3600,   # 1시간마다 연결 재생성
)
```

### 4. 마이그레이션 전 백업

스키마 변경 전에는 항상 데이터베이스를 백업합니다:

```bash
pg_dump -h localhost -U myuser mydb > backup_$(date +%Y%m%d_%H%M%S).sql
```

## 트러블슈팅

### 문제 1: Alembic에서 "Event loop is closed" 오류

**원인**: Alembic 설정에 비동기 연결 문자열을 사용했습니다.

**해결**: `postgres_sync_connection_string`을 사용하도록 변경합니다.

```python
# alembic/env.py
configuration["sqlalchemy.url"] = settings.postgres_sync_connection_string
```

### 문제 2: FastAPI에서 데이터베이스 응답이 느림

**원인**: 동기 드라이버를 사용하여 이벤트 루프가 블로킹됩니다.

**해결**: `postgres_connection_string`을 사용하고 `await`를 올바르게 사용합니다.

```python
# 잘못된 예
result = db.execute(select(User))  # await 없음

# 올바른 예
result = await db.execute(select(User))
```

### 문제 3: SSL 연결 실패

**원인**: SSL 모드가 올바르게 설정되지 않았거나, 인증서 검증에 실패했습니다.

**해결**: SSL 모드를 확인하고 필요한 경우 인증서를 제공합니다.

```bash
# .env
POSTGRES_SSL_MODE=require  # 또는 prefer, verify-ca, verify-full
```

### 문제 4: "asyncpg.exceptions.InvalidPasswordError"

**원인**: 비밀번호에 특수 문자가 포함되어 URL 인코딩이 필요합니다.

**해결**: `urllib.parse.quote_plus()`를 사용하여 비밀번호를 인코딩합니다.

```python
from urllib.parse import quote_plus

@property
def postgres_connection_string(self) -> str:
    password = quote_plus(self.postgres_password.get_secret_value())
    return f"postgresql+asyncpg://{self.postgres_user}:{password}..."
```

## 요약

SQLAlchemy와 FastAPI를 사용하는 비동기 애플리케이션에서는 두 가지 PostgreSQL 연결 문자열이 필요합니다:

1. **`postgres_connection_string`** (`postgresql+asyncpg://`)
   - FastAPI 애플리케이션 런타임용
   - 비동기 드라이버 `asyncpg` 사용
   - 이벤트 루프 내에서 논블로킹 처리
   - `await` 키워드와 함께 사용
   - 높은 동시성과 성능

2. **`postgres_sync_connection_string`** (`postgresql+psycopg2://`)
   - Alembic 마이그레이션 도구용
   - 동기 드라이버 `psycopg2` 사용
   - CLI 환경에서 블로킹 방식으로 실행
   - SSL 설정을 쿼리 파라미터로 포함
   - 스키마 관리 작업 전용

같은 데이터베이스를 가리키지만, 애플리케이션 런타임과 마이그레이션 도구는 근본적으로 다른 실행 모델을 가지고 있습니다. 비동기 애플리케이션은 비동기 드라이버를, 동기 CLI 도구는 동기 드라이버를 필요로 하므로, 각 목적에 맞는 연결 문자열을 사용해야 합니다. 이는 SQLAlchemy와 Alembic을 함께 사용하는 모든 프로젝트에서 나타나는 표준 패턴입니다.
