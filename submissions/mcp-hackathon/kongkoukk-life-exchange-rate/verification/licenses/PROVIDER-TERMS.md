# Third-party provider terms and supplemental dependency licenses

Primary sources read on 2026-09-16. These notes retain the upstream statements checked during submission preparation and explain their application to this artifact. They do not replace the participant's declaration or grant new rights over upstream materials. See the [dependency inventory](DEPENDENCIES.md) and the [complete local license and notice texts](THIRD_PARTY_NOTICES.txt).

## Hosted data sources

| Source | Upstream statement and artifact boundary |
| --- | --- |
| Frankfurter | Its documentation permits free API use, including commercial use, with underlying data subject to each provider's terms. Requests are subject to anti-abuse rate limiting. This project uses the dedicated ECB route and identifies the provider; it does not copy Frankfurter server code. [Documentation](https://frankfurter.dev/) |
| ECB statistics | The reuse policy permits free reuse of public statistics with source attribution and preservation of the statistics and metadata. Third-party data are excluded from that general permission. Preserve captured observations and their source dates; separately label project-derived cross-rate comparisons and impact calculations. [Statistics policy](https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/usage_policy.de.html) |
| ECB website and RSS | The copyright notice requires accurate reproduction and source attribution, and explicit disclosure of modifications. Named-author publications have separate restrictions. This artifact uses headline triggers and structured observations, not complete research papers. [Copyright notice](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html) |
| Federal Reserve Board RSS | Board information is generally public domain unless indicated otherwise; cite the Board. Third-party material and official seals/logos have separate restrictions. Retain headline source links and do not imply endorsement. [Disclaimer](https://www.federalreserve.gov/disclaimer.htm) |
| EIA | EIA permits reuse of government information products with source acknowledgement including publication date. Third-party material, photos and marks have exceptions. EIA Open Data also points users to API terms. The current hosted verification used a synthetic energy fixture; it did not perform keyed EIA calls or imply permission for EIA logos. [Copyright and reuse](https://www.eia.gov/about/copyrights_reuse.php), [Open Data](https://www.eia.gov/opendata/) |

The current evidence retains source URLs, observation timestamps and calculation traces. Its personal profile is explicitly synthetic, and the separately fetched headline is not presented as the cause of the FX change. Provider terms remain applicable when reusing the archived artifact; no ownership over upstream data is claimed.

## Supplement to local dependency inventory

The checked local test environment did not contain these installed distributions or an exact build-backend version. Their unavailable local metadata is supplemented by the following primary published sources, already read on the date above:

- **uvloop 0.22.1:** the version's project page states dual MIT/Apache-2.0 licensing. [PyPI release](https://pypi.org/project/uvloop/0.22.1/)
- **httpx2-jsfetch 1.0:** the version's project page reports BSD-3-Clause. [PyPI release](https://pypi.org/project/httpx2-jsfetch/1.0/)
- **Hatch/Hatchling:** the upstream repository's current license is MIT. This does not establish the exact isolated build-backend version used by Vercel; the project build requirement is not version-pinned in the inspected lock. [Upstream license](https://github.com/pypa/hatch/blob/master/LICENSE.txt)

The first two observations resolve the missing declared-license names, but are not claims that those packages were installed in the local Windows environment. This artifact does not include copied dependency implementations. [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt) preserves all 68 original local license/notice texts that were actually available, under their original relative path labels, with SHA-256 and exact byte lengths. No uvloop, httpx2-jsfetch or Hatch license text has been invented or added to that local-text collection.
