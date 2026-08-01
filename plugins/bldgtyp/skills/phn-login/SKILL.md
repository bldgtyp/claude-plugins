---
description: Replace this machine's PH-Navigator credential through browser approval
disable-model-invocation: true
allowed-tools: Bash(phn-login:*)
---

Run `phn-login`. Tell the user to approve or deny the exact request in the
browser. Do not request, display, copy, or inspect the bearer token. Report only
whether the credential was saved successfully and its file path.
