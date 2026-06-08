# Requirements: HTTPS Captive Portal for BMI30 (EN)

## Quick Instructions

### Objective
Provide a HTTPS portal page on Raspberry with a trusted certificate and no browser certificate warnings on user devices.

### What is required from the administrator
1. Allocate a dedicated subdomain: portal.vinetabmi.cz.
2. Issue a public TLS certificate for portal.vinetabmi.cz (recommended: Let's Encrypt via ACME DNS-01).
3. Enable automatic certificate renewal.
4. Deliver renewed certificate/key to Raspberry automatically.
5. Configure DNS so that inside hotspot network portal.vinetabmi.cz resolves to 10.42.0.1.
6. Allow ports 80 and 443 on Raspberry for hotspot clients.

### Expected result
- Users open the portal over HTTPS without certificate errors.
- Captive flow is triggered by OS HTTP probes, then users are redirected to HTTPS portal.

---

## Detailed Instructions

### 1. Domain and certificate
1. Reserve FQDN: portal.vinetabmi.cz.
2. Issue a certificate from a trusted CA with:
   - CN/SAN: portal.vinetabmi.cz
   - artifacts: fullchain.pem + privkey.pem
3. Configure unattended certificate renewal.
4. Configure post-renew hook to:
   - deliver updated fullchain.pem and privkey.pem to Raspberry;
   - restart HTTPS frontend service (Nginx/Caddy/other).

### 2. DNS
1. Public DNS zone:
   - create record for portal.vinetabmi.cz according to company policy.
2. Local hotspot DNS (dnsmasq on Raspberry):
   - force portal.vinetabmi.cz to resolve to 10.42.0.1.
3. Add CAA records if required by policy.

### 3. Network access
1. Allow hotspot clients to reach:
   - TCP 80 (captive detection/probes);
   - TCP 443 (main HTTPS portal).
2. Ensure firewall/NAT does not block local DNS and HTTP/HTTPS traffic to Raspberry.

### 4. Portal behavior
1. Keep OS probe handling on HTTP port 80.
2. After captive detection, redirect users to HTTPS endpoint:
   - https://portal.vinetabmi.cz/login
3. Do not enable HSTS during initial rollout until stability is validated.

### 5. Deliverables from administrator
1. fullchain.pem
2. privkey.pem
3. optional CA bundle
4. DNS/API parameters (if DNS-01 automation is used)
5. contact person for DNS/PKI ownership

### 6. Acceptance criteria
1. On any client device, https://portal.vinetabmi.cz presents a valid trusted certificate.
2. In hotspot network, portal.vinetabmi.cz resolves to 10.42.0.1.
3. HTTPS portal remains available after Raspberry reboot.
4. Certificate auto-renew process is verified (dry-run or renewal cycle test).
5. Users can access portal without manual certificate installation on phones or PCs.

### 7. Limitation note
A strict 100% guarantee of captive pop-up behavior across all OS/vendor builds is not possible,
but with correct HTTP probe handling and valid HTTPS domain/certificate, user access remains secure and reliable.
