# 1. Improve OpenAlex metadata
## 1.1 Improve 'false positive', i.e wrong links between raw_affiliation_string and country (and RoR)
The harvest-openalex repo extacts from OpenAlex works tagged as 'FR' and upload data in object storage (container openalex).
It then uses our affiliation-matcher to compare the countries computed with the affiliation-matcher and check agains countries in OpenAlex metada. When they disagree, the mismatches are also stored in object storage (container openalex).
Mismatches have been manually checked.
A github issue was opened for OpenAlex team https://github.com/ourresearch/openalex-institution-parsing/issues/5 

## 1.2 Improve 'false negative', i.e missing links wrong links between raw_affiliation_string and country (and RoR)
No explicit dataset produced, but the FOSM data collects links from the institutions themselves (local OSM). first the French OpenScienceMonitor dataset https://storage.gra.cloud.ovh.net/v1/AUTH_32c5d10cb0fe4519b957064a111717e3/bso_dump/bso-publications-latest.jsonl.gz gives links between publications and rors. NB: the RoR linking is coming from the institutions themselves (the ones using the "local" OSM service that we provide https://frenchopensciencemonitor.esr.gouv.fr/declinaisons/bso-locaux - sorry this page has not been translated in english). My point is that these RoRs are not automatically generated, so are trustworthy.
Interesting fields for you in this dataset
 - all_ids : list of ids (doi, hal mainly)
 - rors: list of rors (data coming from institutions)
 - affiliations : list of raw affiliations collected from different sources (crawling etc.)

# 2. Improve FOSM metadata
Three (at least) modules could be improved: crawler (that download raw html), parser (that transforms the html into structured json with affiliations), and then matcher (that infer a country from the affiliation string).
Comparing differences between OpenAlex and FOSM can also help improve FOSM metadata.

Current detected improvement to implement:
 - crawler: 
 - parsers: 
 - matcher:
    - not detected as FR: "French National Institute for Agricultural Research (INRA)", "Triangle : action, discours, pensée politique et économique", "CGG ()", "ESSEC Business School", "European Synchrotron Radiation Facility", "Sorbonne Université", "EMLYON Business School", "Ecole Polytechnique", "Université de Lorraine", "Science Po" ...
    - wrongly detected as FR: "Massachusetts Gen. Hospital, Boston, MA.",     
