#!/bin/bash

set -e

host="http://dumps.wikimedia.org"
language="ptwiki"
date="20150220"

#language="barwiki"
#date="20150305"

#language="enwiki"
#date="20150205"

file="pages-meta-history"
ft="\.xml(-.+)?\.7z$"

dumpdir=/mnt/6000/${language}-dumps
repo=/mnt/6000/${language}-repo

base=${host}/${language}/${date}

oldPWD=${PWD}
mkdir -p ${dumpdir}
cd ${dumpdir}

curl -s ${base}/${language}-${date}-md5sums.txt | grep -E "${file}" | grep -E "${ft}" > md5sums

echo "Downloading dumps"
while IFS=" " read sum fn
do
    echo "Downloading: ${fn} "
    wget --quiet --show-progress --continue ${base}/${fn}
done < md5sums

echo ""
echo "Checking md5sums"
md5sum -c md5sums 

cd ${oldPWD}

echo ""
echo "Importing into git"

rm -rf .import-*
rm -rf ${repo}
git init --bare ${repo}

rm -f IMPORT

function do_import(){
    while IFS=" " read sum fn
    do
        7z -so x ${dumpdir}/${fn} | ./import.py -w -m -1 --only-blobs
    done < ${dumpdir}/md5sums

    ./import.py -w
}

do_import | GIT_DIR=${repo} git fast-import
