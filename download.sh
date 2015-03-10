#!/bin/bash

set -e

#
# Configuration options
#

# What we will be importing today
#language="ptwiki"
#date="20150220"
#language="barwiki"
#date="20150305"
language="enwiki"
date="20150205"

# Where are the dumps going to be
dumpdir=/mnt/6000/${language}-dumps

# Where is the output repo
repo=/mnt/6000/${language}-repo

# Where to get the dumps
host="http://dumps.wikimedia.org"

# History files. Not much to worry about here.  I chose 7z for the filetype, as
# it's the smallest choice currently. Be sure to change the main while loop
# below if you choose otherwise.
file="pages-meta-history"
ft="\.xml(-.+)?\.7z$"

# Some internal filenames
metafile=".import-${language}-meta"
commfile=".import-${language}-comm"
pagefile=".import-${language}-page"
userfile=".import-${language}-user"
markfile=".import-${language}-mark" # stores marks used by git fast-import
progfile=".import-${language}-prog" # stores last file completed

#
# The remainder of this file is the actual script.
#
base=${host}/${language}/${date}

mkdir -p ${dumpdir}

curl -s ${base}/${language}-${date}-md5sums.txt \
    | grep -E "${file}" | grep -E "${ft}" > ${dumpdir}/md5sums

echo "Downloading dumps"
while IFS=" " read sum fn; do
    echo "Downloading: ${fn} "
    wget --quiet --show-progress --continue ${base}/${fn} -O ${dumpdir}/${fn}
done < ${dumpdir}/md5sums


oldPWD=${PWD}
cd ${dumpdir}

echo ""
echo "Checking md5sums"
md5sum -c md5sums

cd ${oldPWD}

echo ""
echo "Importing into git"

if [ -s ${progfile} || ! -f ${progfile} ]; then
    echo "Progress file ${profile} not found, starting anew."
    rm -rf ${markfile} ${metafile} ${commfile} ${userfile} ${pagefile}
    rm -rf ${repo}
    git init --bare ${repo}
    touch ${progfile}
else
    echo "*************************************************************"
    echo "*      Found old progress file ${profile}, resuming.        *"
    echo "* Ctrl-C and remove ${progfile} if this was not your intent *"
    echo "*************************************************************"
    for each in $(seq 5 1); do
        echo "$each... "
        sleep 1
    done
    echo "Ding! Resuming"
fi

# import blobs, create metadata
while IFS=" " read sum fn; do
    if ! grep -q "^${fn}$" ${progfile}; then
        #
        # extract | levitate | import
        #
        7z -so x ${dumpdir}/${fn} \
            | ./levitation.py -w -m -1 --only-blobs \
                --metafile=${metafile} \
                --commfile=${commfile} \
                --userfile=${userfile} \
                --pagefile=${pagefile} \
            | GIT_DIR=${repo} git fast-import \
                --import-marks-if-exists=${markfile} \
                --export-marks=${markfile}
        echo ${fn} >> ${progfile}
    fi
done < ${dumpdir}/md5sums

# create the commits
./levitation.py -w | GIT_DIR=${repo} git fast-import --import-marks=${marksfile}

# let git clean up a few bytes now that we're done.
GIT_DIR=${repo} git gc
