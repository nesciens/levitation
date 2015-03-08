# Levitation 

This is Levitation, a project to convert Wikipedia database dumps into Git
repositories. It has been successfully tested with a small Wiki
(bar.wikipedia.org) having 12,200 articles and 104,000 revisions. Importing
those took 6 minutes on a Core 2 Duo 1.66 GHz. RAM usage is minimal: Pages are
imported one after the other, it will at most require the amount of memory
needed to keep all revisions of a single page into memory. You should be safe
with 1 GB of RAM.

See below ("Things that work") for the current status.

Some knowledge of Git is required to use this tool. And you will probably need
to edit some variables in the source code.

You need at least Python 3.3.

## Example usage

See `download.sh` for a full example and usable script.

This will import the pdc.wikipedia.org dump into a new Git repository `repo`:

    rm -rf repo; git init --bare repo && \
        ./import.py < ~/pdcwiki-20091103-pages-meta-history.xml | \
        GIT_DIR=repo git fast-import | \
        sed 's/^progress //'

Please note that there’s the flag, `-m` that defaults to 100 so Levitation will
only import 100 pages, not more. This protects you from filling your disk when
you’re too impatient. ;) Set it to -1 when you’re ready for a "real" run.
Execute `import.py --help` to see all available options.

### How it should be done

You can get recent dumps of all Wikimedia wikis at:
http://download.wikimedia.org/backup-index.html

The "pages-meta-history.xml" files are what we want. It includes all pages
in all namespaces and all of their revisions.

Alternatively, you may use a MediaWiki’s "Special:Export" page to create an XML
dump of certain pages.

### Things that work

- Read a Wikipedia XML full-history dump and output it in a format suitable for
  piping into git-fast-import(1). The resulting repository contains one file
  per page. All revisions are available in the history. There are some
  restrictions, read below.
- Use the original modification summary as commit message.
- Read the Wiki URL from the XML file and set user mail addresses accordingly.
- Use the author name in the commit instead of the user ID.
- Store additional information in the commit message that specifies page and
  revision ID as well as whether the edit was marked as “minor”.
- Use the page’s name as file name instead of the page ID. Non-ASCII characters
  and some ASCII ones will be replaced by “.XX”, where .XX is their hex value.
- Put pages in namespace-based subdirectories.
- Put pages in a configurably deep subdirectory hierarchy.
- Use command line options instead of hard-coded magic behavior. Thanks to
  stettberger for adding this.
- Use a locally timezoned timestamp for the commit date instead of an UTC one.
- Allow IPv6 addresses as IP edit usernames. 

### Things that are broken

- Ordering is by the revisions of a single page, not by time.

### Things that are strange

- Since we use subdirectories, the Git repo is no longer larger than the
  uncompressed XML file, but instead about 30% of it. This is good. However, it
  is still way larger than the bz2 compressed file, and I don’t know why.

### Things that are cool

- `git checkout master~30000` takes you back 30,000 edits -- and on my
  test machine it only took about a second.
- The XML data might be in the wrong order to directly create commits from it,
  but it is in the right order for blob delta compression: When passing blobs
  to git-fast-import, delta compression will be tried based on the previous
  blob -- which is the same page, one revision before. Therefore, delta
  compression will succeed and save you tons of storage.

## Storage requirements

- `maxrev` is the highest revision ID in the dump.
- `maxpage` is the highest page ID in the dump.
- `maxuser` is the highest user ID in the dump.
- The revision metadata storage needs maxrev*141 bytes.
- The revision comment storage needs maxrev*383 bytes.
- The author name storage needs maxuser*383 bytes.
- The page title storage needs maxpage*383 bytes.

Those files can be deleted after an import.

Additionally, the content itself needs some space. My test repo was about 15%
the size of the uncompressed XML, that is about 300% the size of the bz2
compressed XML data (see "Things that are strange").

Note that if you want to check out a working copy, the filesystem it will be
living on needs quite a few free inodes. If you get "no space left on device"
errors with plenty of space available, that's what hit you.

## Contact

Contacting the (original) author:

This monster is written by Tim "Scytale" Weber. It is an experiment, whether the
current "relevance war" in the German Wikipedia can be ended by decentralizing
content.

Find the guys and gals around this project in freenode #levitation, or talk
directly to me via http://scytale.name/contact/ or Twitter (@Scytale).

## LICENSE

This whole bunch of tasty bytes is licensed under the terms of the WTFPLv2.
