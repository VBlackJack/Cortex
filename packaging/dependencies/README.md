# Pinned release dependencies

## Confluence console converter 1.2.0

`confluence-console-source-v1.2.0.zip` is a minimal source archive produced
from the immutable `v1.2.0` tag of
`https://github.com/VBlackJack/confluence-rag-builder`.

- SHA-256: `8ea2b538b44022fd32bd2f06add6f3c21c15a9cd29b9e1a60c6e234c8421e86d`
- Included projects: Core, Console, and their two test projects
- Included license: Apache-2.0 `LICENSE`

The release workflow verifies the archive hash, rebuilds the console project,
runs its focused test suite, and checks the `--probe` capability contract
before embedding the published executable in the Windows installer.

Rebuild the archive from a clean clone with:

```powershell
git archive --format=zip `
  --output=confluence-console-source-v1.2.0.zip `
  v1.2.0 `
  Directory.Build.props LICENSE `
  src/ConfluenceRAGBuilder.Core `
  src/ConfluenceRAGBuilder.Console `
  tests/ConfluenceRAGBuilder.Core.Tests `
  tests/ConfluenceRAGBuilder.Console.Tests
```
