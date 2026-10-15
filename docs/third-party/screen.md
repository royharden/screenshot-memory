# Offline text-screen source attribution

The six modules in `src/screenshot_memory/shared/screen/` and the contract README
in `contracts/vendor/screen/` are copied unchanged from
royharden/github-issue-triage commit
`419eaf97f605637a9aece2f43c25b04ccb3dabdf`, tree
`c31ea3f6b97b3385cacb9c9f679fd2f60183d1a7`.
The original MIT notice is retained as `screen-LICENSE.md` here.

| Original path under src/issue_triage/shared/screen | SHA256 of exact Git bytes |
| --- | --- |
| __init__.py | 847da0a534d478e8be45e2de1eef47613bc3f1058ed85e6b5c5f9e99b222e42b |
| models.py | 1d33ba786df2cdbd81bd944ad69c11108d220fa268eca4960b4c51dcf1bab252 |
| prepare.py | 955e21a840cf00e56b7d431e3d0cf5aa2a5cd66de3e61433a054f31249bdb9dc |
| questions.py | 663ad1437f6abc709caa5b0115051f6eee41debfd41a74e213895651fd47aec8 |
| rules.py | c0b8920063f0eb3157d44cc76995a459e40267c78d9a5feab3c706ae85357a9b |
| typed.py | 54022116c9c8bdade586f60cca058f90709a43e24fddef109bbcea2bac7d92bc |

Owner test_screen.py source SHA256
`3c2ba42b14a8909135a8a9bd5f0079a7fb50294c9b2fdf7176c55f1b709eee47`
is adapted only for the consumer namespace imports and detached source lookup.
All original test scenarios remain present. Injected typed gateway spies are
synthetic and do not establish actual canonical provider or ledger integration.
The portable runtime uses only Python 3.12 stdlib. No SDK, source lookup, storage
or transport is installed by this module.
