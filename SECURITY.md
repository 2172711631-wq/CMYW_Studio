# Security policy

## Scope

CMYW Studio is a local desktop and command-line tool. It reads an image file you choose
and writes a 3MF file. It does not open network connections, does not phone home, and
does not upload your images anywhere.

The most relevant risk is therefore **untrusted input**: the tool parses images with
OpenCV and writes archives with Python's `zipfile`. If you process images from an
untrusted source, the usual advice for image parsers applies.

## Reporting

For anything you believe is exploitable, please use GitHub's
[private vulnerability reporting](https://github.com/2172711631-wq/CMYW_Studio/security/advisories/new)
rather than a public issue, and allow a little time for a fix before disclosing.

For ordinary bugs and crashes, a normal issue is the right place.

## Supported versions

The latest release on the `main` branch is the only supported version.
