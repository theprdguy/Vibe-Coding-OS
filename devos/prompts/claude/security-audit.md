# Security Audit (OWASP A01~A10 + STRIDE)

> `ticket.security_audit: true` 또는 인증/결제/권한/외부 입력 ticket에 자동 적용.
> secrets scan(gitleaks)은 박힌 키만 잡음. 인증 흐름·권한 결함은 별도 검토 필요.

## 한계 명시 (정직)

이 prompt는 GStack `/cso`의 *prompt 부분*만 차용. 원본의 22MB ML 분류기, Haiku 투표, canary 토큰 같은 인프라는 미차용. 효과 70~80%. **출시 임팩트가 큰 영역(payment 처리 등)은 외부 보안 감사 별도 의뢰 필수**.

Prompt portion adapted from gstack /cso — Copyright (c) 2026 Garry Tan, MIT (https://github.com/garrytan/gstack).

## 적용 절차 (CLAUDE1)

1. ticket의 도메인 식별
2. 해당 도메인 + 공통 항목 검토
3. 발견을 BLOCKER/WARNING으로 분류 (adversarial review와 동일 severity)
4. 결과를 PR review에 통합 또는 ticket의 dod 보강 사유로 사용

---

## OWASP Top 10 (2021)

### A01: Broken Access Control
- [ ] **IDOR**: 다른 유저의 ID로 endpoint 호출 → 401/403 반환?
- [ ] **Privilege escalation**: 일반 유저가 admin endpoint 호출 → 차단?
- [ ] **Forced browsing**: 인증 미들웨어 우회 가능한 라우트?
- [ ] **CORS misconfiguration**: `Access-Control-Allow-Origin: *` + credential?
- [ ] **JWT 검증**: `alg: none` 허용? signature 검증 누락?
- [ ] **Default deny**: 모든 라우트 기본 차단, 명시적 allow?

### A02: Cryptographic Failures
- [ ] **비밀번호 hash**: bcrypt/scrypt/argon2 사용? cost factor 충분?
- [ ] **전송 암호화**: HTTPS 강제? HSTS 헤더?
- [ ] **저장 암호화**: PII가 DB에 평문?
- [ ] **약한 알고리즘**: MD5/SHA1 사용? DES?
- [ ] **하드코딩 secret**: 코드에 API key/JWT secret?
- [ ] **CSRF token**: 제거됐다면 SameSite=Strict 쿠키 대체?

### A03: Injection
- [ ] **SQL injection**: parameterized query 강제? string concat?
- [ ] **NoSQL injection**: MongoDB query 직접 user input?
- [ ] **Command injection**: shell 호출 시 user input?
- [ ] **LDAP injection**: 검색 필터에 user input?
- [ ] **XSS**: 출력 시 escape? markdown/HTML 허용 시 sanitize 라이브러리?
- [ ] **HTML/XML injection**: feed/RSS 출력?

### A04: Insecure Design
- [ ] **Threat model**: 이 기능에 위협 모델 작성됐는가? (STRIDE 섹션 참조)
- [ ] **Rate limiting**: brute force 방지?
- [ ] **Lockout**: 계정 잠금 정책?
- [ ] **Idempotency**: 결제·중요 작업 idempotency key?
- [ ] **Business logic abuse**: 음수 수량, 환불 후 재환불 등?

### A05: Security Misconfiguration
- [ ] **기본 credential**: admin/admin 활성? 첫 setup 강제 변경?
- [ ] **에러 메시지**: stack trace 노출? DB 에러 그대로?
- [ ] **불필요한 기능**: 디버그 endpoint 남아 있음?
- [ ] **Header**: X-Frame-Options, CSP, X-Content-Type-Options 설정?
- [ ] **버전 노출**: Server header, X-Powered-By 노출?
- [ ] **개발 도구**: GraphQL playground, /admin 접근 제한?

### A06: Vulnerable and Outdated Components
- [ ] **의존성 audit**: `npm audit`, `pip-audit`, `cargo audit` CI 실행?
- [ ] **EOL 라이브러리**: 보안 패치 안 받는 버전?
- [ ] **Pinning**: lockfile 커밋?
- [ ] **CVE 모니터링**: dependabot/renovate 활성?

### A07: Identification and Authentication Failures
- [ ] **Brute force**: rate limit + lockout?
- [ ] **Credential stuffing**: 알려진 leak password 차단? (haveibeenpwned API)
- [ ] **Session fixation**: 로그인 후 session ID 재발급?
- [ ] **Weak password policy**: min length, charset?
- [ ] **2FA backup code**: 1회용? hashed 저장?
- [ ] **Password reset**: 토큰 단일 사용? 시간 제한?

### A08: Software and Data Integrity Failures
- [ ] **CI/CD pipeline**: untrusted source에서 dependency 가져옴?
- [ ] **Auto-update**: signature 검증?
- [ ] **Deserialization**: pickle/yaml.load() user input?
- [ ] **CSP**: script-src 제한? eval/inline 차단?

### A09: Security Logging and Monitoring Failures
- [ ] **Auth event 로그**: login/logout/lockout/password reset 모두 기록?
- [ ] **PII 마스킹**: 로그에 비밀번호/토큰/카드번호?
- [ ] **타임스탬프**: UTC + ISO 8601?
- [ ] **로그 무결성**: append-only? 외부 저장?
- [ ] **Alert**: 연속 실패, 권한 escalation 시 알림?

### A10: Server-Side Request Forgery (SSRF)
- [ ] **외부 URL fetch**: user-supplied URL → 내부 메타데이터 endpoint(169.254.169.254) 차단?
- [ ] **URL allowlist**: 호출 가능한 도메인 화이트리스트?
- [ ] **Redirect 추적**: 외부 redirect → 내부 IP 차단?
- [ ] **Webhook**: 우리 서버 → 외부 지정 URL, 외부 → 우리 처리 모두 검증?

---

## STRIDE Threat Modeling

ticket 기능에 대해 6개 카테고리별 위협 식별.

### S — Spoofing (정체 위조)
- [ ] 다른 사용자로 위장 가능? (session 탈취, JWT 위조)
- [ ] 시스템/서비스로 위장 가능? (DNS spoofing, MITM)
- [ ] 익명 호출이 인증된 호출처럼 보일 수 있는가?

### T — Tampering (변조)
- [ ] 클라이언트가 서버 결정 변조 가능? (가격, 권한)
- [ ] 전송 중 변조? (HTTPS 강제, signature)
- [ ] DB row 직접 변조 시 검증? (audit log, checksum)

### R — Repudiation (부인)
- [ ] 사용자 행위 증거 보존? (감사 로그, 서명된 영수증)
- [ ] 로그 변조 방지? (append-only, 외부 저장)

### I — Information Disclosure (정보 노출)
- [ ] 에러 메시지에 PII?
- [ ] 응답 차이로 user enumeration 가능? (signup 시 "이미 존재" vs "성공")
- [ ] 디버그 정보 노출? (stack trace, version)
- [ ] timing attack으로 정보 추출? (string 비교)

### D — Denial of Service
- [ ] Rate limit?
- [ ] 무거운 query 차단? (timeout, complexity limit)
- [ ] 파일 업로드 size limit?
- [ ] regex DoS (ReDoS) 가능?

### E — Elevation of Privilege (권한 상승)
- [ ] 일반 → admin 경로?
- [ ] 다른 tenant 데이터 접근?
- [ ] OS-level command 실행 가능?

---

## 출력 형식

```markdown
## Security Audit — T-XXX

### 적용 도메인
- OWASP: A01, A02, A07 (예: 인증 ticket)
- STRIDE: S, I, E

### Findings
#### BLOCKER 1
- **OWASP**: A01 (Broken Access Control)
- **STRIDE**: E (Elevation of Privilege)
- **Location**: `apps/api/src/auth/middleware.py:45`
- **Issue**: JWT의 `role` claim을 클라이언트가 변조 가능 (signature 검증 누락)
- **Evidence**: <코드 인용 또는 PoC>
- **Required Action**: <구체적 수정 방향>

### WARNING 1 ...

### 외부 감사 권장 여부
- [ ] 출시 임팩트 큼 (payment, PII at scale, multi-tenant) → 외부 보안 감사 별도 의뢰 필요
```

## Anti-patterns

- "내부 도구라 보안 안 중요" → 모든 적용. 내부 도구가 가장 자주 침해됨.
- "이 라이브러리는 안전하다고 들었음" → 직접 검증. CVE 확인.
- "test 환경이라 hardcoded OK" → secrets는 항상 env. 누군가 prod에 commit함.
- "OWASP 항목 다 통과" → STRIDE도 적용. 새 위협은 표준에 없음.

## 참조
- `devos/prompts/claude/prd-intake-checklist.md` — 도메인별 강제 질문
- `devos/prompts/claude/review-adversarial.md` — severity 형식 통합
- `devos/AI.md` Ticket Standard `security_audit` 필드
- OWASP Top 10 (2021): https://owasp.org/Top10/
