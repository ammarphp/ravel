# Published likelihood — ATLAS-SUSY-2018-16 compressed-spectra search (background workspace)

`BkgOnly.json.gz` is the background-only HistFactory workspace of the compressed-spectra search
(arXiv:1911.12606, ATLAS-SUSY-2018-16), gzip-compressed without a name or timestamp. The
decompressed bytes are the HEPData likelihood original: 1,988,103 bytes, sha256
`f609ddbe3a6f43f01f3ec2725c8244009a750fba349f3698e292a1deaa73b282`, 38 channels (32 slepton
signal regions in ee and mm and six control regions), POI `mu_SIG`.

Provenance: HEPData record ins1767649, resources tab, "Likelihoods" archive (CC BY 4.0).

It is the workspace that the shipped channel maps
`src/ravel/data/likelihoods/channel_maps/susy-2018-16-compressed-*.json` bind to; see
`src/ravel/data/likelihoods/registry.json` for the exact scope and the omissions each map
declares. The signal patches of the publication are not shipped; a native yield file is
converted with `sa2json_native` and one of those maps.
