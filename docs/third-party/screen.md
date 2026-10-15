# Offline text-screen source attribution

The seven modules in `src/screenshot_memory/shared/screen/` and the contract README
in `contracts/vendor/screen/` are copied from the owner project github-issue-triage
successor commit `8f8bb88ffc4148611dd6180b6f01d264c367cce3`, tree
`8fda4a904a6eeeb6badcd06af5d0ce067f35cdfb`. The five original rules/preparation/
models/questions/package-init files remain byte-identical to the earlier
`419eaf97f605637a9aece2f43c25b04ccb3dabdf` source. The typed implementation is an
intentional controlled upgrade, and s3_adapter.py is new; neither is labelled
unchanged from the original edition. All current modules preserve their exact
successor Git bytes. Existing canonical S3 siblings are reused without duplication.
The original MIT notice is retained as `screen-LICENSE.md` here.

| Original path under src/issue_triage/shared/screen | SHA256 of exact Git bytes |
| --- | --- |
| __init__.py | 847da0a534d478e8be45e2de1eef47613bc3f1058ed85e6b5c5f9e99b222e42b |
| models.py | 1d33ba786df2cdbd81bd944ad69c11108d220fa268eca4960b4c51dcf1bab252 |
| prepare.py | 955e21a840cf00e56b7d431e3d0cf5aa2a5cd66de3e61433a054f31249bdb9dc |
| questions.py | 663ad1437f6abc709caa5b0115051f6eee41debfd41a74e213895651fd47aec8 |
| rules.py | c0b8920063f0eb3157d44cc76995a459e40267c78d9a5feab3c706ae85357a9b |
| typed.py | 50a40aeb850693c4f10d3ea8a4a1e263819e9bd3a5c9a1681d9ec58be14f4bfb |
| s3_adapter.py | fb5956b91fab5cf4fc992926b9f35b9c44f9bcfac61ec013126adc5d7495ae60 |

Owner test_screen.py source SHA256
`3c2ba42b14a8909135a8a9bd5f0079a7fb50294c9b2fdf7176c55f1b709eee47`
is adapted only for the consumer namespace imports and detached source lookup.
All original test scenarios remain present. The native successor's public tests
add real offline canonical S3 ledger/controller checks; the same published
synthetic Rig is reused after an exact namespace-only byte-equivalence check.
Combined moved tests verify actual class identity. Legacy gateway spies remain
synthetic. Rules/preparation are Python3.12 stdlib; the explicit native path also
uses the existing canonical S3/Pydantic2.14.1 closure. No live SDK, source lookup,
durable payload cache or transport is installed by this module.
