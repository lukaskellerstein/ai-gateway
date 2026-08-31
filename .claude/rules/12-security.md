# Reference: Security and secrets

Two rules, in order. The first settles most cases.

## 1. Default — the secret never enters the repository

A secret that was never committed cannot leak, cannot be scraped out of git history, and
does not depend on a key staying safe. Prefer this every time.

| Kind of secret | Lives in |
|:--|:--|
| Personal API keys, tokens | `~/.secrets/secrets.enc.yaml` — age-encrypted, outside every repo, delivered by `~/Projects/.envrc`. Never exported from `.zshrc`: a shell-wide export is inherited by every child process, including every `npm install` hook |
| Per-project runtime config | `.env` / `.envrc` — **gitignored**, with a tracked `.env.example` carrying the *names* and empty values |
| CI credentials | the CI provider's own secret store |
| Cloud / cluster credentials | the provider's keychain, `~/.kube/config`, `~/.aws/` — never copied in |

If a repo has no `.gitignore` entry for `.env`, `.envrc` and `*.key`, add one before
writing anything that could land there.

## 2. Exception — when a secret must be versioned with the code

Kubernetes `Secret` manifests, Helm values, CI config, a deploy-time compose file. For
those, and **only** those, the answer is **SOPS + age**. Never plaintext, never base64
(that is encoding, not encryption), never a hand-rolled scheme.

Setup is one file per repo — copy it, do not write one from memory:

```bash
cp ~/Projects/Github/lukaskellerstein/mac-setup/projects/templates/sops.yaml .sops.yaml
```

The private key is `~/.config/sops/age/keys.txt` and is never in any repo. Encrypted files
carry an `.enc.` infix — it is what `.sops.yaml` matches, and it makes them obvious in
review.

> [!warning]
> On macOS sops does **not** look there. Its default is
> `~/Library/Application Support/sops/age/keys.txt`, so decryption needs
> `SOPS_AGE_KEY_FILE=$HOME/.config/sops/age/keys.txt` in the environment. Encrypting works
> without it; only decrypting fails, so the symptom appears later and elsewhere.
> `failed to load age identities` is this and nothing more sinister.

| Task | Command |
|:--|:--|
| Create / edit | `sops edit secrets.enc.yaml` |
| Encrypt an existing file | `sops -e -i secrets.enc.yaml`, then verify it changed |
| Read one value | `sops -d --extract '["db"]["password"]' secrets.enc.yaml` |
| Run something with the values as env | `sops exec-env env.enc.yaml 'the-command'` |
| Apply to a cluster | `sops -d secrets.enc.yaml \| kubectl apply -f -` |

`exec-env` and the pipe form exist so the decrypted content never touches the disk — prefer
them. `exec-env` accepts only a **flat** map; a nested file fails with `cannot use complex
value in environment`. Keep env-shaped secrets in their own flat file and use
`-d --extract` for structured ones.

## Never

- **Never `sops -d file > file.plain`.** That is how plaintext gets committed. Use
  `sops edit`, `exec-env`, or a pipe.
- **Never commit a decrypted file.** If one exists after debugging, delete it and check
  `git status` before reporting.
- **Never reformat an encrypted file.** SOPS stores a MAC over the values; reindenting
  invalidates it and the file stops decrypting — a corruption that only surfaces at deploy
  time. Exclude `*.enc.*` from any formatter or hook.
- **Never commit `keys.txt`, `*.agekey`, or any age private key**, and never paste one into
  a chat, an issue or a log.
- **Never print a decrypted secret** into output, a commit message, a log line or a test
  fixture. Report *that* a value was read, not the value.
- **Never keep a plaintext credential file**, gitignored or not — every session and tool
  can read it and it never expires. Treat one you find as a found secret: report it, move
  the value into SOPS, delete the file, recommend rotation.
- **Never invent an alternative** — no `openssl enc`, no git-crypt, no committed encrypted
  zip. One scheme per machine is what makes it reviewable.

## When you find a secret already committed

Say so immediately and stop. **Rotating the credential at the provider comes first** —
history rewriting is secondary and never sufficient alone, because the value is already in
every clone and on every forge that mirrored it. Do not rewrite history unasked.

The contract behind this file is `projects/claude-code.md` in mac-setup.
