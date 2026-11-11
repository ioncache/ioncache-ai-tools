# Changelog

Release notes are grouped into New, Updated and Fixed, based on Git history
since the previous version. Historical release boundaries and dates come from
plugin version changes in Git. Version-only release commits are omitted.

## 1.9.2 (2026-11-11)

### New

* None.

### Updated

* remove automatic scope and answer reviews ([#46](https://github.com/ioncache/ioncache-ai-tools/issues/46)) ([1f9f193](https://github.com/ioncache/ioncache-ai-tools/commit/1f9f19398f05976b963cd9ea6b22cb090bf9aee8))
* restore skill discovery and direct invocation ([#43](https://github.com/ioncache/ioncache-ai-tools/issues/43)) ([61c548d](https://github.com/ioncache/ioncache-ai-tools/commit/61c548de2c899a18f7093ac0d47da0c577f7df42))
* streamline README and retire roadmap ([#42](https://github.com/ioncache/ioncache-ai-tools/issues/42)) ([4318b9e](https://github.com/ioncache/ioncache-ai-tools/commit/4318b9e67ca28173956286afdd1ef227d90d5d17))

### Fixed

* check Node before creating worktrees ([#44](https://github.com/ioncache/ioncache-ai-tools/issues/44)) ([fe6762a](https://github.com/ioncache/ioncache-ai-tools/commit/fe6762ab8a080656973809cc36b1b25efc8612c9))
* enforce the worktree Node version requirement ([#45](https://github.com/ioncache/ioncache-ai-tools/issues/45)) ([7a83a52](https://github.com/ioncache/ioncache-ai-tools/commit/7a83a52b99a39e3f807fe4e5002c94a488e4fd9b))

## 1.9.1 (2026-11-09)

### New

* **review:** improve coverage and report handoffs ([#39](https://github.com/ioncache/ioncache-ai-tools/issues/39)) ([55390c8](https://github.com/ioncache/ioncache-ai-tools/commit/55390c8d0523d20ceeaf1ba5418f41099c442ba9))

### Updated

* None.

### Fixed

* None.

## 1.9.0 (2026-11-09)

### New

* **config:** reconcile feature settings and retire claim checks ([#38](https://github.com/ioncache/ioncache-ai-tools/issues/38)) ([503437c](https://github.com/ioncache/ioncache-ai-tools/commit/503437c73d981cb3eeeb249c80e65f6c87b68723))

### Updated

* added repo level AGENTS.md ([c869070](https://github.com/ioncache/ioncache-ai-tools/commit/c8690704e72616599f6a4c9d6473b243b06eb76a))

### Fixed

* None.

## 1.8.1 (2026-11-07)

### New

* None.

### Updated

* backfilled changelog ([1f69b7d](https://github.com/ioncache/ioncache-ai-tools/commit/1f69b7d77f3c4c0a47aae71b57f64b5391428ce5))

### Fixed

* **hooks:** preserve approval context and denial evidence ([#37](https://github.com/ioncache/ioncache-ai-tools/issues/37)) ([71fed42](https://github.com/ioncache/ioncache-ai-tools/commit/71fed4249a675c3e4fd8364c7f8f76a162f8cb49))

## 1.8.0 (2026-11-07)

### New

* add shared documentation lookup cache ([#30](https://github.com/ioncache/ioncache-ai-tools/issues/30)) ([c5c2c89](https://github.com/ioncache/ioncache-ai-tools/commit/c5c2c89ff3652e05c7a63649b1ce9a7d77a10647))
* add shared review orchestration ([#32](https://github.com/ioncache/ioncache-ai-tools/issues/32)) ([937598f](https://github.com/ioncache/ioncache-ai-tools/commit/937598f4176ca211ec9a914753f0458c6d6f39ba))
* add system-level engineering judgment ([#35](https://github.com/ioncache/ioncache-ai-tools/issues/35)) ([cd3b6a7](https://github.com/ioncache/ioncache-ai-tools/commit/cd3b6a7c479b84ca82f347b4cd38d89a74ad0d64))
* add versioned changelog tooling ([#36](https://github.com/ioncache/ioncache-ai-tools/issues/36)) ([a44ddda](https://github.com/ioncache/ioncache-ai-tools/commit/a44ddda49d725d8edf7a83a4021d331d6a15124b))

### Updated

* **skills:** make PR comments brief and conversational ([#33](https://github.com/ioncache/ioncache-ai-tools/issues/33)) ([f3facf9](https://github.com/ioncache/ioncache-ai-tools/commit/f3facf9d34234cd640ae13d19aecfdbb71fd57a2))

### Fixed

* enable shared docs cache across all harnesses ([#31](https://github.com/ioncache/ioncache-ai-tools/issues/31)) ([4bf6877](https://github.com/ioncache/ioncache-ai-tools/commit/4bf68777ed4c4633e07a3453c4ec2863e2dbd3a0))
* **hooks:** reduce recurring context with bounded turn enforcement ([#34](https://github.com/ioncache/ioncache-ai-tools/issues/34)) ([3d9201a](https://github.com/ioncache/ioncache-ai-tools/commit/3d9201af467e40eb9c34585e7152d2e5a641ba44))

## 1.7.0 (2026-11-05)

### New

- Add reusable PR writing skill (#28) ([4154456](https://github.com/ioncache/ioncache-ai-tools/commit/415445678eeb664aa5b74dbb63f3658f445ede4b)).

### Updated

- None.

### Fixed

- Clarify and streamline PR review comments (#29) ([fc3f867](https://github.com/ioncache/ioncache-ai-tools/commit/fc3f867fa1e9b31b994dafd08bbb432c10ad437f)).

## 1.6.0 (2026-11-04)

### New

* add draft PR review comment skill ([#25](https://github.com/ioncache/ioncache-ai-tools/issues/25)) ([f2aaaf4](https://github.com/ioncache/ioncache-ai-tools/commit/f2aaaf4eddeaee9417de32ed3926a23142e4cfb7))
* add read-only review and triage loop ([#26](https://github.com/ioncache/ioncache-ai-tools/issues/26)) ([1265032](https://github.com/ioncache/ioncache-ai-tools/commit/1265032c6f845f028707b84891545c3ca3fd760b))

### Updated

* enforce conventional commit messages ([#27](https://github.com/ioncache/ioncache-ai-tools/issues/27)) ([503b0d6](https://github.com/ioncache/ioncache-ai-tools/commit/503b0d60aaab69c2de8a10228b358dd0e8bc245b))

### Fixed

* None.

## 1.5.1 (2026-10-28)

### New

* None.

### Updated

* None.

### Fixed

* focus dependency review reports on project breakage ([#24](https://github.com/ioncache/ioncache-ai-tools/issues/24)) ([d5469ac](https://github.com/ioncache/ioncache-ai-tools/commit/d5469ace4c74ca8826afcce3e286081fe4f03204))

## 1.5.0 (2026-10-28)

### New

* add dependency-aware Dependabot PR review skill ([#23](https://github.com/ioncache/ioncache-ai-tools/issues/23)) ([4ee9a87](https://github.com/ioncache/ioncache-ai-tools/commit/4ee9a87c5e4c1deb194af1d6f53cf59d82b54348))

### Updated

* release 1.5.0 and document dependency review skill ([f6cb71c](https://github.com/ioncache/ioncache-ai-tools/commit/f6cb71cb7027a8b0bd89ee24df2999934448390c))

### Fixed

* improve guardrails and workflow recovery ([#21](https://github.com/ioncache/ioncache-ai-tools/issues/21)) ([7187ec5](https://github.com/ioncache/ioncache-ai-tools/commit/7187ec5a58fb479cd329500be799f437be7f0039))

## 1.4.2 (2026-10-19)

### New

* None.

### Updated

* None.

### Fixed

* **hooks:** disable the claim-evidence guard ([#18](https://github.com/ioncache/ioncache-ai-tools/issues/18)) ([162440c](https://github.com/ioncache/ioncache-ai-tools/commit/162440c39a0c5622c88064c6f37fc8cc2556790e))
* permit evidence reviews during question turns ([64b0fef](https://github.com/ioncache/ioncache-ai-tools/commit/64b0fefbc96d9c25c504b2295cc46bcebc572835))

## 1.4.1 (2026-10-02)

### New

* add autonomous review and fix loops ([#15](https://github.com/ioncache/ioncache-ai-tools/issues/15)) ([be32d64](https://github.com/ioncache/ioncache-ai-tools/commit/be32d64ce0aad6ef9e4e84e441578953b08a0ef4))
* **hooks:** add complete-source claim evidence guard ([#16](https://github.com/ioncache/ioncache-ai-tools/issues/16)) ([8d0e762](https://github.com/ioncache/ioncache-ai-tools/commit/8d0e762a74e2578f8d4960276b9605f4db1133f8))
* upgrade codex functionality ([a1fce24](https://github.com/ioncache/ioncache-ai-tools/commit/a1fce243452211ba645314e5b4c4f64ff319a52a))

### Updated

* **dev:** updated repo level copilot instructions ([bef5ab4](https://github.com/ioncache/ioncache-ai-tools/commit/bef5ab48b5c744c6bba7f40ffc84af52e19c9228))
* **docs:** updated README ([f3f47e6](https://github.com/ioncache/ioncache-ai-tools/commit/f3f47e6938104dea419fb0f04ad83f75615b0b49))

### Fixed

* **hooks:** correct guard parsing and evidence boundaries ([#17](https://github.com/ioncache/ioncache-ai-tools/issues/17)) ([9745f66](https://github.com/ioncache/ioncache-ai-tools/commit/9745f6642058f973da9679ef51a4cc650a978d89))
* **hooks:** handle rule-discovery failures ([#14](https://github.com/ioncache/ioncache-ai-tools/issues/14)) ([438c214](https://github.com/ioncache/ioncache-ai-tools/commit/438c214080418b4613a2e004ba043663e77569e9))
* improve cross-harness hook reliability and workflow portability ([#13](https://github.com/ioncache/ioncache-ai-tools/issues/13)) ([64f2f48](https://github.com/ioncache/ioncache-ai-tools/commit/64f2f4884f46adedee2c65580d43df40e0a18e02))

## 1.4.0 (2026-09-29)

### New

* add GitHub Copilot CLI plugin support ([#12](https://github.com/ioncache/ioncache-ai-tools/issues/12)) ([4b0465f](https://github.com/ioncache/ioncache-ai-tools/commit/4b0465fb78670f797fbbcafcdb9e2e83682ba717))

### Updated

* **dev:** added initial copoilot instructions ([272f415](https://github.com/ioncache/ioncache-ai-tools/commit/272f4150ddc7f2f920075e296add0b47653d7b6c))

### Fixed

* None.

## 1.3.0 (2026-09-29)

### New

* **hooks:** remove git commit/push authorization guards ([#11](https://github.com/ioncache/ioncache-ai-tools/issues/11)) ([1790e05](https://github.com/ioncache/ioncache-ai-tools/commit/1790e05cca42f3c3e43dae3318ab7368accd0984))

### Updated

* None.

### Fixed

* None.

## 1.2.0 (2026-09-21)

### New

* added .graphifyignore to create worktree ([031fd2d](https://github.com/ioncache/ioncache-ai-tools/commit/031fd2dbab5f93efddc6f666dc06a3702167914f))
* **rules:** add never_push_without_asking ([#5](https://github.com/ioncache/ioncache-ai-tools/issues/5)) ([1d86aa4](https://github.com/ioncache/ioncache-ai-tools/commit/1d86aa49c3764916045b48e5e08d14d3378b94f2))

### Updated

* document plugin reinstall and removal ([80adbd1](https://github.com/ioncache/ioncache-ai-tools/commit/80adbd1357b4229d11e7c2ae0063241a65dab04e))
* undo push authorization hooks ([#5](https://github.com/ioncache/ioncache-ai-tools/issues/5)) ([3ba7965](https://github.com/ioncache/ioncache-ai-tools/commit/3ba79655d8b208da9ba4fcb8d0119c9820e646ac))
* undo push-hook false-positive fixes ([#7](https://github.com/ioncache/ioncache-ai-tools/issues/7)) ([ef4f608](https://github.com/ioncache/ioncache-ai-tools/commit/ef4f608d65685a39b228d1e6e7819b0056b1bd1b))
* updated README ([0f877e1](https://github.com/ioncache/ioncache-ai-tools/commit/0f877e1c37da20f6b5c8a1a618d2bea8fd89772c))
* updated README structure ([acbf74b](https://github.com/ioncache/ioncache-ai-tools/commit/acbf74b3f74d98443d2957870ac84cd0cc08a628))

### Fixed

* **hooks:** clarify that only mutating tools are blocked on a pending question ([#4](https://github.com/ioncache/ioncache-ai-tools/issues/4)) ([bb2c6d0](https://github.com/ioncache/ioncache-ai-tools/commit/bb2c6d02912f14b4cd2d98e7762e321461826644))
* **hooks:** rebuild the git authorization guard on the captured prompt ([#8](https://github.com/ioncache/ioncache-ai-tools/issues/8)) ([119fc14](https://github.com/ioncache/ioncache-ai-tools/commit/119fc14280e7b24cd54342a367b0d395b439f3b9))
* **hooks:** stop the git push hook denying unrelated commands ([#7](https://github.com/ioncache/ioncache-ai-tools/issues/7)) ([3b48fbc](https://github.com/ioncache/ioncache-ai-tools/commit/3b48fbce51c0e28c716b8081dcd12670ec0ca713))
* **hooks:** unpunctuated questions and pending-question bypasses ([#2](https://github.com/ioncache/ioncache-ai-tools/issues/2)) ([ca6eca5](https://github.com/ioncache/ioncache-ai-tools/commit/ca6eca5378c12466c0eb110658fecce34840299b))

## 1.1.0 (2026-09-14)

### New

* add documentation-writing skill, license, and CI validation ([6adfeed](https://github.com/ioncache/ioncache-ai-tools/commit/6adfeed6e4415167dbdff25addf9f85fad223fd2))
* added a docs first skill ([e98a079](https://github.com/ioncache/ioncache-ai-tools/commit/e98a079430f8972541bc6c8c9cb75379508fcc08))
* **codex:** add plugin support and shared skills and commands ([68bddfb](https://github.com/ioncache/ioncache-ai-tools/commit/68bddfb6e3fdec72ac4c1b4507045baf49cf8f0a))
* **hooks:** add generic rule engine ([#1](https://github.com/ioncache/ioncache-ai-tools/issues/1)) ([1e34afc](https://github.com/ioncache/ioncache-ai-tools/commit/1e34afce208047eb21ad2dae6b2329b3994855ac))

### Updated

* organize README reference tables ([87f5633](https://github.com/ioncache/ioncache-ai-tools/commit/87f563377596a5c4bf03fafdf5a22749ce929fa7))
* use repository owner in installation examples ([5f34e65](https://github.com/ioncache/ioncache-ai-tools/commit/5f34e65640a5fc03673d4fc3087f7e7e1c4e50e5))

### Fixed

* None.

## 1.0.0 (2026-07-29)

### New

* None.

### Updated

* initialize plugin scaffolding ([6de9f96](https://github.com/ioncache/ioncache-ai-tools/commit/6de9f96b7bd368afcea6290fcaeae14402e6a23d))

### Fixed

* None.
