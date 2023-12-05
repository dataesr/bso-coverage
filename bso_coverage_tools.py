from dotenv import load_dotenv
import hashlib
import json
import os
import requests
import subprocess
from enum import Enum
import pandas as pd
import swiftclient
from pprint import pprint

load_dotenv()

url_upw = "http://135.125.83.210"
ALEX_DOI_PREFIX = "https://doi.org/"
DATE_MIN = 2013
DATE_MAX = 2021
ES_HOST = "https://cluster.elasticsearch.dataesr.ovh"
ES_INDEX = "bso-publications"

ES_TOKEN = os.getenv("ES_TOKEN")
OVH_OS_KEY = os.getenv("OVH_OS_KEY")
OVH_OS_PROJECT_ID = os.getenv("OVH_OS_PROJECT_ID")
OVH_OS_USER = os.getenv("OVH_OS_USER")

STATES = {
    "UNDEFINED": "Publication is undefined",
    "DOI_FOUND": "Publication DOI has been found",
    "CRAWLED": "Publication has been crawled",
    "PARSED": "Publication has been parsed",
    "PARSED_FR": "Publication has been parsed with french affiliation",
    "IN_FOSM": "Publication is present in French Open Science Monitor",
    "IN_FOSM_FR": "Publication is present in French Open Science Monitor with french affiliation",
}

ERRORS = {
    "BAD_DOI": "DOI is incorrect",
    "DOI_NO_ACCESS": "Unable to access DOI webpage",
    "DOI_NO_CROSSREF": "DOI not in Crossref",
    "DOI_NO_UNPAYWALL": "DOI not in Unpaywall",
    "DOI_NO_PUBLICATION_YEAR": "DOI no publication year in Unpaywall",
    "DOI_EARLY_PUBLICATION_YEAR": f"DOI published before {DATE_MIN} in Unpaywall",
    "DOI_LATE_PUBLICATION_YEAR": f"DOI published after {DATE_MAX} in Unpaywall",
    "NOT_PARSED_FR": "No french publication detected in parsed publication",
    "NOT_PARSED": "Landing page has not been parsed",
    "NOT_CRAWLED": "Landing page has not been crawled",
    "ALEX_DOI_NOT_FOUND": "OpenAlex 'DOI' object is empty",
    "ALEX_AUTHORSHIPS_NOT_FOUND": "OpenAlex 'authorships' object is empty",
    "ALEX_YEAR_NOT_FOUND": "OpenAlex 'publication_year' object is empty",
    "ALEX_TYPE_NOT_FOUND": "OpenAlex 'type' object is empty",
    "FOSM_YEAR_NOT_FOUND": "FOSM 'year' object is empty",
    "FOSM_TYPE_NOT_FOUND": "FOSM 'genre' object is empty",
    "MISMATCH_YEAR": "FOSM and OpenAlex publication year mismatch",
    "MISMATCH_TYPE": "FOSM and OpenAlex publication type mismatch",
    "MISMATCH_FRENCH_AFFILIATION": "FOSM and OpenAlex french affiliation matcher mismatch",
}


class State(Enum):
    UNDEFINED = 0
    DOI_FOUND = 1
    CRAWLED = 2
    PARSED = 3
    PARSED_FR = 4
    IN_FOSM = 5
    IN_FOSM_FR = 6


class Error(Enum):
    OK = 0
    BAD_DOI = 1
    DOI_NO_ACCESS = 2
    DOI_NO_CROSSREF = 3
    DOI_NO_UNPAYWALL = 4
    DOI_NO_PUBLICATION_YEAR = 5
    DOI_EARLY_PUBLICATION_YEAR = 6
    DOI_LATE_PUBLICATION_YEAR = 7
    NOT_PARSED_FR = 8
    NOT_PARSED = 9
    NOT_CRAWLED = 10
    ALEX_DOI_NOT_FOUND = 11
    ALEX_AUTHORSHIPS_NOT_FOUND = 12
    ALEX_TYPE_NOT_FOUND = 13
    ALEX_YEAR_NOT_FOUND = 14
    FOSM_TYPE_NOT_FOUND = 15
    FOSM_YEAR_NOT_FOUND = 16
    MISMATCH_TYPE = 17
    MISMATCH_YEAR = 18
    MISMATCH_FRENCH_AFFILIATION = 19


def state_str(state: State) -> str:
    state_name = state.name if isinstance(state, State) else state
    state_txt = STATES[state_name] if state_name in STATES else f"Unknown state {state_name}"
    return state_txt


def error_str(error: Error) -> str:
    error_name = error.name if isinstance(error, Error) else error
    error_txt = ERRORS[error_name] if error_name in ERRORS else f"Unknown error {error_name}"
    return error_txt


def cli_process(filename, container):
    init_swift_cmd = f"swift -q --os-auth-url https://auth.cloud.ovh.net/v3 --auth-version 3 --key {OVH_OS_KEY} --user {OVH_OS_USER} --os-user-domain-name Default --os-project-domain-name Default --os-project-id {OVH_OS_PROJECT_ID} --os-project-name Alvitur --os-region-name GRA"
    cmd_count = f"{init_swift_cmd} list {container} -p {filename} | wc -l"
    count = subprocess.check_output(cmd_count, shell=True)
    return int(count) == 1


def cli_download(obj, container):
    init_swift_cmd = f"swift -q --os-auth-url https://auth.cloud.ovh.net/v3 --auth-version 3 --key {OVH_OS_KEY} --user {OVH_OS_USER} --os-user-domain-name Default --os-project-domain-name Default --os-project-id {OVH_OS_PROJECT_ID} --os-project-name Alvitur --os-region-name GRA"
    cmd_count = f"{init_swift_cmd} download {container} {obj}"
    subprocess.check_output(cmd_count, shell=True)


def swift_connection():
    return swiftclient.Connection(
        authurl="https://auth.cloud.ovh.net/v3",
        user=OVH_OS_USER,
        key=OVH_OS_KEY,
        os_options={
            "user_domain_name": "Default",
            "project_domain_name": "Default",
            "project_id": OVH_OS_PROJECT_ID,
            "project_name": "Alvitur",
            "region_name": "GRA",
        },
        auth_version="3",
    )


def swift_process(filename, container, conn):
    return conn.head_object(container, filename)


def swift_download(obj, container, conn):
    head, contents = conn.get_object(container, obj)
    with open(obj.replace("/", ""), "wb") as f:
        f.write(contents)


def get_hash(x):
    hashed = hashlib.md5(x.encode("utf-8")).hexdigest()
    return hashed


def get_doi_and_id(url):
    notice_id = url
    init = "url"
    doi = None
    if "doi.org" in url:
        doi = url.replace("http://", "").replace("https://", "").replace("dx.", "").replace("doi.org/", "").strip()
        init = doi.split("/")[0]
        notice_id = "doi{}".format(doi)
    id_hash = get_hash(notice_id)

    filename = "{}/{}.json.gz".format(init, id_hash)
    return doi, notice_id, id_hash, filename


def is_present(doi, container, cli=True, conn=None):
    doi_url = f"https://doi.org/{doi}"
    crawled_file_path = get_doi_and_id(doi_url)[-1]

    if cli:
        return cli_process(crawled_file_path, container)
    else:
        try:
            swift_process(crawled_file_path, container, conn)
            return True
        except:
            return False


def is_crawled(doi, cli=True, conn=None):
    return is_present(doi, "landing-page-html", cli, conn)


def is_parsed(doi, cli=True, conn=None):
    return is_present(doi, "parsed", cli, conn)


def is_parsed_fr(doi, cli=True, conn=None):
    return is_present(doi, "parsed_fr", cli, conn)


def download(obj, container, cli=True, conn=None):
    if cli:
        cli_download(obj, container)
    else:
        swift_download(obj, container, conn)


def get_parsed(doi, cli=True, conn=None):
    doi_url = f"https://doi.org/{doi}"
    crawled_file_path = get_doi_and_id(doi_url)[-1]
    download(crawled_file_path, "parsed", cli, conn)
    return pd.read_json(crawled_file_path.replace("/", "")).to_dict(orient="records")[0]


def get_html(doi, cli=True, conn=None):
    doi_url = f"https://doi.org/{doi}"
    crawled_file_path = get_doi_and_id(doi_url)[-1]
    download(crawled_file_path, "landing-page-html", cli, conn)
    return pd.read_json(crawled_file_path.replace("/", "")).to_dict(orient="records")[0]


def analyse_doi(doi):
    # See here : https://gist.github.com/brews/8d3b3ede15d120a86a6bd6fc43859c5e
    doi_url = f"https://doi.org/{doi}"
    doi_status_code = requests.get(doi_url, headers={"accept": "application/citeproc+json"}).status_code
    if doi_status_code != 200:
        return (Error.DOI_NO_ACCESS, ("doi_status_code", doi_status_code))

    # Check DOI from Crossref
    crossref_url = f"https://api.crossref.org/works/{doi}/agency"
    crossref_json = requests.get(crossref_url).json()
    agency = crossref_json.get("message").get("agency").get("id")
    if agency != "crossref":
        return (Error.DOI_NO_CROSSREF, ("agency", agency))

    # Check if DOI is in Unpaywall
    unpaywall_url = f"https://api.unpaywall.org/v2/{doi}?email=bso@recherche.gouv.fr"
    unpaywall_response = requests.get(unpaywall_url)
    if unpaywall_response.status_code != 200:
        return (Error.DOI_NO_UNPAYWALL, ("status_code", unpaywall_response.status_code))

    publication_year = unpaywall_response.json().get("published_date")
    if publication_year is None:
        return (Error.DOI_NO_PUBLICATION_YEAR, None)

    publication_year = int(publication_year[:4])
    if publication_year < DATE_MIN:
        return (Error.DOI_EARLY_PUBLICATION_YEAR, ("publication_year", publication_year))
    if publication_year > DATE_MAX:
        return (Error.DOI_LATE_PUBLICATION_YEAR, ("publication_year", publication_year))

    return (Error.OK, None)


def affiliation_matcher_is_french(affiliation):
    # Affiliation matcher request
    req = requests.post(
        "https://affiliation-matcher.staging.dataesr.ovh/match",
        json={"type": "country", "query": affiliation},
    )
    matched_countries = req.json().get("results", [])

    # Detect french affiliation
    if "fr" in list(map(str.lower, matched_countries)):
        return True

    return False


def french_affiliations_from_openalex_work(alex_work):
    # Initialization
    alex_french_affiliations = []

    # Get OpenAlex authorships object
    alex_authorships = alex_work["authorships"] if "authorships" in alex_work else None
    if not alex_authorships:
        return alex_french_affiliations

    # Find french raw affiliation
    alex_authorships = alex_authorships if isinstance(alex_authorships, list) else [alex_authorships]
    for author in alex_authorships:
        alex_countries = author.get("countries") or []
        raw_affiliation = author.get("raw_affiliation_string") or "Undefined"
        if "fr" in list(map(str.lower, alex_countries)):
            alex_french_affiliations.append(raw_affiliation)
    return alex_french_affiliations


def analyse_publication_year_from_work(fosm_work, alex_work):
    # Get OpenAlex publication year
    alex_year = alex_work["publication_year"] if "publication_year" in alex_work else None
    if not alex_year:
        return (Error.ALEX_YEAR_NOT_FOUND, None)

    # Get FOSM publication year
    fosm_year = fosm_work.get("_source").get("year") if "_source" in fosm_work else fosm_work.get("year")
    if not fosm_year:
        return (Error.FOSM_YEAR_NOT_FOUND, None)

    # Analyse publication year
    if fosm_year != alex_year:
        return (Error.MISMATCH_YEAR, (fosm_year, alex_year))

    return (Error.OK, None)


def analyse_publication_type_from_work(fosm_work, alex_work):
    # Get OpenAlex publication type
    alex_type = alex_work["type"] if "type" in alex_work else None
    if not alex_type:
        return (Error.ALEX_TYPE_NOT_FOUND, None)

    # Get FOSM publication type
    fosm_type = fosm_work.get("_source").get("genre") if "_source" in fosm_work else fosm_work.get("genre")
    if not fosm_type:
        return (Error.FOSM_TYPE_NOT_FOUND, None)

    if fosm_type != alex_type:
        return (Error.MISMATCH_TYPE, (fosm_type, alex_type))

    return (Error.OK, None)


def analyse_work(
    doi: str, alex_work: dict | pd.Series | pd.DataFrame = None, cli: bool = True, as_pandas: bool = True
):
    """Coverage analysis of a work

    Args:
        doi (str): Work Digital Object Identifier
        alex_work (dict | pd.Series | pd.DataFrame): OpenAlex work object. Defaults to None.
        cli (bool, optional): Enable command line for swift calls. Defaults to True.
        as_pandas (bool, optional): Return result as pd.Series instead of dict. Defaults to True.

    Returns:
        dict | pd.Series: Result of analysis
    """

    # Initialization
    error = Error.OK
    error_data = None
    state = State.UNDEFINED
    conn = None
    result = {}

    # Get data from FOSM
    fosm_doi_url = f"{ES_HOST}/{ES_INDEX}/_search?q=doi.keyword:%22{doi}%22"
    fosm_response = requests.get(fosm_doi_url, headers={"Authorization": f"Basic {ES_TOKEN}"}).json()
    fosm_hits_n = fosm_response.get("hits").get("total").get("value")

    # Several DOI found in FOSM - should not happen
    if fosm_hits_n > 1:
        error = Error.BAD_DOI

    # DOI found in FOSM
    if fosm_hits_n == 1:
        state = State.IN_FOSM

    # DOI not found in FOSM
    if fosm_hits_n < 1:
        # Swift connection
        if not cli:
            conn = swift_connection()
            auth = conn.get_auth()

        # Parsing fr
        if state == State.UNDEFINED:
            if is_parsed_fr(doi, cli, conn):
                state = State.PARSED_FR
            else:
                error = Error.NOT_PARSED_FR

        # Parsing
        if state == State.UNDEFINED:
            if is_parsed(doi, cli, conn):
                state = State.PARSED
            else:
                error = Error.NOT_PARSED

        # Crawling
        if state == State.UNDEFINED:
            if is_crawled(doi, cli, conn):
                state = State.CRAWLED
            else:
                error = Error.NOT_CRAWLED

        # Check DOI
        if state == State.UNDEFINED:
            error, error_data = analyse_doi(doi)
            if error.value > Error.DOI_NO_ACCESS.value:
                state = State.DOI_FOUND

    # Publication detected countries
    if error == Error.OK and state in [State.IN_FOSM]:
        fosm_detected_countries = fosm_response.get("hits").get("hits")[0].get("_source").get("bso_country") or []
        if "fr" in list(map(str.lower, fosm_detected_countries)):
            state = State.IN_FOSM_FR

    if error == Error.OK and alex_work is not None:
        # Check alex data
        if isinstance(alex_work, pd.DataFrame) and pd.DataFrame.shape[0] == 1:
            alex_work = alex_work.squeeze()
        if isinstance(alex_work, dict):
            alex_work = pd.Series(alex_work)
        if not isinstance(alex_work, pd.Series):
            raise TypeError(f"Input should be {dict}, {pd.Series} or {pd.DataFrame} not {type(alex_work)}")

        if error == Error.OK and state in [State.PARSED, State.IN_FOSM]:
            # OpenAlex detected countries
            alex_french_affiliations = french_affiliations_from_openalex_work(alex_work)

            # Matcher for french affiliations
            if error == Error.OK:
                match_fr = False
                for french_affiliation in alex_french_affiliations:
                    match_fr = affiliation_matcher_is_french(french_affiliation)
                    if match_fr:
                        break

                if match_fr is False:
                    error = Error.MISMATCH_FRENCH_AFFILIATION
                    error_data = alex_french_affiliations

        # Publication year
        if error == Error.OK and state in [State.IN_FOSM, State.IN_FOSM_FR]:
            error, error_data = analyse_publication_year_from_work(fosm_response.get("hits").get("hits")[0], alex_work)

        # Publication type
        if error == Error.OK and state in [State.IN_FOSM, State.IN_FOSM_FR]:
            error, error_data = analyse_publication_type_from_work(fosm_response.get("hits").get("hits")[0], alex_work)

    # Result as dict
    result = {
        "doi": doi,
        "last_state": state.name,
        "last_error": error.name,
        "last_error_data": error_data,
    }

    if as_pandas:
        return pd.Series(result)

    return result


def analyse_from_openalex_work(
    alex_work: dict | pd.Series | pd.DataFrame, cli: bool = True, as_pandas: bool = True
) -> dict | pd.Series:
    """Coverage analysis of an OpenAlex work

    Args:
        alex_work (dict | pd.Series | pd.DataFrame): OpenAlex work object.
        cli (bool, optional): Enable command line for swift calls. Defaults to True.
        as_pandas (bool, optional): Return result as pd.Series instead of dict. Defaults to True.

    Returns:
        dict | pd.Series: Result of analysis
    """

    # Check input data type
    if isinstance(alex_work, pd.DataFrame) and pd.DataFrame.shape[0] == 1:
        alex_work = alex_work.squeeze()
    if isinstance(alex_work, dict):
        alex_work = pd.Series(alex_work)
    if not isinstance(alex_work, pd.Series):
        raise TypeError(f"Input should be {dict}, {pd.Series} or {pd.DataFrame} not {type(alex_work)}")

    # Check input data fields
    if "doi" not in alex_work:
        raise KeyError("'doi' key not found in input data")

    # Get publication DOI
    doi = alex_work["doi"].removeprefix(ALEX_DOI_PREFIX)

    # Analyse work
    result = analyse_work(doi, alex_work=alex_work, cli=cli, as_pandas=as_pandas)

    return result


def analyse_from_openalex(alex_df: dict | pd.DataFrame, cli: bool = True, as_pandas: bool = True) -> pd.DataFrame:
    """Coverage analysis of OpenAlex works

    Args:
        alex_df (dict | pd.DataFrame): OpenAlex works object.
        cli (bool, optional): Enable command line for swift calls. Defaults to True.
        as_pandas (bool, optional): Return result as pd.DataFrame instead of dict. Defaults to True.

    Returns:
        pd.DataFrame: Results of analysis
    """

    # Convert input if needed
    if isinstance(alex_df, dict) or isinstance(alex_df, pd.Series):
        alex_df = pd.DataFrame(alex_df)
    if not isinstance(alex_df, pd.DataFrame):
        raise TypeError(f"Input should be {dict} or {pd.DataFrame} not {type(alex_df)}")

    # Apply analyse
    applied_df = alex_df.apply(
        lambda row: analyse_from_openalex_work(row, cli=cli, as_pandas=False), axis="columns", result_type="expand"
    )

    if not as_pandas:
        return applied_df.reset_index().to_dict()

    return applied_df.reset_index()


def analyse_from_doi(
    doi: str, openalex_api: bool = True, cli: bool = True, as_pandas: bool = True
) -> dict | pd.Series:
    """Coverage analysis of work

    Args:
        doi (str): Work Digital Object Identifier
        openalex_api (bool, optional): whether to check openalex api or not. Defaults to True.
        cli (bool, optional): Enable command line for swift calls. Defaults to True.
        as_pandas (bool, optional): Return result as pd.Series instead of dict. Defaults to True.

    Returns:
        dict | pd.Series: Result of analysis
    """

    # Initialization
    alex_work = None

    # Get open alex info
    if openalex_api:
        alex_response = requests.get(f"https://api.openalex.org/works/https://doi.org/{doi}")
        alex_work = pd.Series(alex_response.json()) if alex_response.status_code == 200 else None

    # Analyse work
    result = analyse_work(doi, alex_work, cli=cli, as_pandas=as_pandas)

    return result


def analyse_from_dois(
    dois: str | list | pd.Series, openalex_api: bool = True, cli: bool = True, as_pandas: bool = True
) -> pd.DataFrame:
    """Coverage analysis of works

    Args:
        dois (str | list | pd.Series): Works Digital Object Identifiers
        openalex_api (bool, optional): whether to check openalex api or not. Defaults to True.
        cli (bool, optional): Enable command line for swift calls. Defaults to True.
        as_pandas (bool, optional): Return result as pd.DataFrame instead of list. Defaults to True.

    Returns:
        pd.DataFrame: Results of analysis
    """

    # Convert input if needed
    if isinstance(dois, str):
        dois = list(dois)
    if isinstance(dois, pd.Series):
        dois = dois.to_list()
    if not isinstance(dois, list):
        raise TypeError(f"Input should be {str}, {list} or {pd.Series} not {type(dois)}")

    # Apply analyse
    applied = list(map(lambda doi: analyse_from_doi(doi, cli=cli, as_pandas=False), dois))

    if as_pandas:
        return pd.DataFrame(applied).reset_index()

    return applied
