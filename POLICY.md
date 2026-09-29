# Usage / policy notes

1. Only archive videos/audio/subtitles that you have the right to download and redistribute.
2. Do not use this repository to circumvent YouTube DRM, authentication controls, geographic restrictions, paywalls, or access controls.
3. Keep GitHub Actions usage tied to the repository's legitimate automation purpose. Do not turn the workflow into a general-purpose downloader service.
4. Do not use GitHub Releases as a high-volume public video CDN.
5. Keep the daily check lightweight. Do metadata/format inspection before media download.
6. Keep Actions artifacts short-lived; they are a staging mechanism, not permanent storage.
7. Respect channel/content requests and platform terms where applicable.

This repository deliberately has configurable limits so an accidental channel configuration cannot create unbounded CI usage.
