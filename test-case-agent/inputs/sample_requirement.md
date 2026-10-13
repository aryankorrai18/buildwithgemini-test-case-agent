# User Story: User Authentication & Account Security

**As a** registered customer,  
**I want to** securely log in to my account with my email and password,  
**So that** I can access my private dashboard and manage my profile.

---

## Features & Business Rules

1. **Credentials Validation (REQ-1)**:
   - User enters registered email address and password.
   - Email format must be valid (standard RFC 5322 format, e.g. `user@domain.com`).
   - Passwords are case-sensitive.
   - Successful login redirects user to `/dashboard` with an HTTP-only secure session cookie and resets the failed login attempt counter.

2. **Account Lockout Policy (REQ-2)**:
   - If a user inputs an invalid password 5 consecutive times, the account status changes to `LOCKED` for 15 minutes.
   - Subsequent attempts during lockout must immediately return: `"Account locked. Please try again after 15 minutes or reset your password."` without validating the password.
   - Lockout timer resets automatically after 15 minutes of inactivity.

3. **Rate Limiting & Abuse Prevention (REQ-3)**:
   - IP-based rate limiting allows a maximum of 10 login requests per minute per IP.
   - Exceeding the rate limit returns HTTP 429 Too Many Requests with a `Retry-After` header.

4. **Input Constraints & UI Requirements (REQ-4)**:
   - Email field maximum length is 254 characters; cannot be blank or contain leading/trailing whitespace.
   - Password field maximum length is 128 characters; cannot be blank.
   - Password input field must be masked (type="password") with an optional "Show/Hide Password" toggle button.

5. **Session Management & Remember Me (REQ-5)**:
   - Standard session expires after 30 minutes of inactivity.
   - If "Remember Me" is checked, the session token remains valid for 30 days unless explicitly logged out.
   - Logging in on a new device triggers a security email notification to the user's registered email address.
