# Release signing

Windows releases can be Authenticode-signed by the release workflow when the repository has a publicly trusted publisher certificate.

1. Obtain an Authenticode code-signing certificate issued to the publisher shown in the installer (`Das Kreb`). The certificate authority will verify the publisher's identity.
2. Export the certificate and private key as a password-protected PFX file. Keep the PFX private.
3. Base64-encode the PFX file and add these repository **Actions secrets** under **Settings → Secrets and variables → Actions**:
   - `WINDOWS_SIGNING_PFX_BASE64`: the base64-encoded PFX contents.
   - `WINDOWS_SIGNING_PFX_PASSWORD`: the PFX password.
4. Publish a new version tag. The workflow signs and verifies the app executables and installer before attaching them to the release.

When these secrets are absent, the workflow publishes unsigned Windows executables. A trusted signature identifies the publisher and can reduce security warnings, but SmartScreen reputation takes time to build and individual antivirus products make their own detection decisions. Do not use a self-signed certificate to try to establish public trust.
