# Levitation 

This is Levitation, a project to convert Wikipedia database dumps into Git
repositories.

This is a fork of the [original project](https://github.com/scy/levitation) by
Tim "Scytale" Weber.

This tool is meant for use with `git fast-import`. There is a lot of manual
lifting to do.

## Requirements

You will need at least Python 3.3. If you need Python 2.x... well, good luck
with your fork.

Storage requirements are as follows.

- Let `maxrev`, `maxpage`, and `maxuser` be the highest revision ID, page ID,
  and user ID in the dump.
- The revision metadata storage needs maxrev*141 bytes.
- The revision comment storage needs maxrev*258 bytes.
- The author name storage needs maxuser*258 bytes.
- The page title storage needs maxpage*258 bytes.

Those files can be deleted after an import.

Additionally, the content itself needs some space. My repos are about 9x the
size of the 7z dumps.

Note that if you want to check out a working copy, the filesystem it will be
living on needs quite a few free inodes. If you get "no space left on device"
errors with plenty of space available, that's what hit you.

## Example usage

See `download.sh` for a full example and usable script.

Essentially, the tool chain looks like this:

    XML output | levitation | git fast-import

If you're trying to stuff Wikipedia into git, I assume you understand how to
use [pipes](https://en.wikipedia.org/wiki/Pipeline_%28Unix%29) effectively. If
not, hit me up on Twitter ([@excsc](http://twitter.com/excsc)) and I'll help.

This will import the pdc.wikipedia.org dump into a new Git repository `repo`:

    git init --bare repo
    cat ~/pdcwiki-20091103-pages-meta-history.xml \
    | ./levitation.py \
    | GIT_DIR=repo git fast-import \
    | sed 's/^progress //' # optional

Please note that there's the `-m` flag that defaults to 100. This makes
Levitation only import 100 pages, not more. This protects you from filling your
disk when you’re too impatient. ;) Set it to -1 when you’re ready for a "real"
run. Execute `levitation.py --help` to see all available options.

### Getting dumps

You can get recent dumps of all Wikimedia wikis at:
http://dumps.wikimedia.org/backup-index.html

The "pages-meta-history" files are what we want. It includes all pages in all
namespaces and all of their revisions. Go for the 7z versions if available.

Alternatively, you may use a MediaWiki’s "Special:Export" page to create an XML
dump of certain pages. *Note: That hasn't been tested on this fork.*

## Status & Features

- Read a Wikipedia XML full-history dump and output it in a format suitable for
  piping into git-fast-import(1). The resulting repository contains one file
  per page. All revisions are available in the history. There are some
  restrictions, read below.
- Use the original modification summary as commit message.
- Read the Wiki URL from the XML file and set user mail addresses accordingly.
- Use the author name in the commit instead of the user ID.
- Store additional information in the commit message that specifies page and
  revision ID as well as whether the edit was marked as "minor".
- Put pages in namespace-based subdirectories.
- Put pages in a configurably deep subdirectory hierarchy.
- Use command line options instead of hard-coded magic behavior. Thanks to
  stettberger for adding this.
- Use a locally timezoned timestamp for the commit date instead of an UTC one.
- Allow IPv6 addresses as IP edit usernames. 
- Support multi-part dumps without needing to recombine them.
- Process files in chunks.
- Resuming from the last processed dump.

## Contributing

1. Fork this repository
2. Create a new branch to work on
3. Commit your tests and/or changes
4. Push and create a pull request here!
5. :beers:

## LICENSE

This fork has been moved to use the MIT License, with the original author's (Tim
"Scytale" Weber) blessing.

See the `LICENSE` file for more info.
