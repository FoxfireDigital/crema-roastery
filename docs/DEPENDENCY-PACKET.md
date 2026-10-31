# Dependency review packet

Crema's own application and build helpers use the repository's MIT license. Upstream code, fonts, browser assets, operating-system packages and container layers retain their own terms. A package's top-level license does not relicense bundled components. Customer records, credentials, original artwork and roast profiles are installation data and are excluded from the generic release input.

The review packet should identify the exact source revision, platform, image IDs, registry digests and release archive checksums. Keep installed Python/Debian inventories, compiled Go modules, native-file hashes, dynamic linkage, available license/notice texts, upstream wheel manifests, vulnerability reports and scoped dispositions together. Captured inventories use documented custom formats; they are not presented as validated SPDX/CycloneDX conformance or legal certification.

## Source and notice material

* Exact Debian/PostgreSQL source packages: source-version identities, .dsc files, original source archives and packaging changes, with checksums verified. Record maintainer-signature verification separately from download/hash verification.
* Exact Python source archives and their primary metadata/checksums. The image retains the Psycopg-C, Pillow and CFFI source used by its native build, plus generated wheel hashes and builder-package/tool versions.
* Pinned Go module sources/checksums and compiled-component notices for Caddy and gosu, with their matching toolchain source. A complete module-cache archive may include test/build-only modules; identify the compiled subset separately.
* The cryptography source lockfile, exact registry-crate sources/checksums, its wheel SBOM and the observed bundled OpenSSL source/version. Local Rust crates are part of the cryptography source tree. Preserve its alternative-license choices and notices for review.
* The matching CPython source/build identity and CA trust-bundle source. Removed build tooling and public placeholders in upstream image layers remain part of the upstream-layer provenance; runtime removal does not rewrite a base layer.
* Bundled asset notices outside dist-info, including Django browser libraries and ReportLab fonts. The notice collector now retains these too. DarkGarden's font terms include a document-embedding exception; that is a component-specific term for review, not a general relicensing of the container. Determine the required preferred source/replacement material for each applicable component.

Review LGPL terms for Psycopg and any other applicable native components using their exact license texts, source/build material and the actual distribution method. The Dockerfiles, pinned build inputs, source archives and layer records support rebuilding/replacement analysis. Their existence alone is not a complete license-compliance decision. Do not assume exceptions from another database-driver version.

## Completion and publication

For every component, record the version/hash, provenance, notices, source association, relevant advisory assessment, remaining questions and reviewer/date. Keep unresolved items visible. A maintainer can prepare and validate the technical packet; independent security and qualified licensing review remain separate gates. Neither a successful build nor an advisory count of zero replaces them.

Publish the complete approved source/notices material through the same release process as any approved binary images, with retention/replacement instructions as applicable. The initial artifacts are private review material. No source or image is made public by the packet tools, and no blanket statement that the container is entirely MIT is justified.
