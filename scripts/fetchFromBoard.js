import fetch from 'node-fetch';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { TOKEN } from './secrets.js'

console.log('fetching from board...')

// these are files we want to not even bring down from the board
// there are other files we may bring down but gitignore (secrets.py & settings.toml) 
const IGNORE = [
  '.fseventsd',
  '.metadata_never_index',
  '.Trashes',
  'boot_out.txt',
  '._code.py',
  '._secrets.py',
  '._settings.toml',
  '._boot_out.txt'
];

/*
  Workflow:
    - edit code in the browser with "web workflow"
    - execute this script to copy code to this directory
    - use normal git workflow to commit and push upstream
*/

async function fetchFS (path = '') {
  const url = `http://cpy-5970ec.local/fs/${path}`;
  console.log(`fetching filesystem from ${url}`)
  const resp = await fetch(url, {
    // credentials: "include",
    headers: {
        Accept: "application/json",
        Authorization: `Basic ${TOKEN}`
    },
    "referrer": "http://cpy-5970ec.local/code/",
    // 'mode': 'cors'
  });
  return resp.json();
}

async function fetchFile (file = '') {
  const resp = await fetch(`http://cpy-5970ec.local/fs/${file}`, {
    // "credentials": "include",
    headers: {
        Accept: '*/*',
        'Authorization': `Basic ${TOKEN}`
    },
    // "mode": "cors"
  });
  return resp.text();
}

async function processFiles(path = '') {
  const data = await fetchFS(path);

  for (const entry of data) {
    if (!IGNORE.includes(entry.name)) {
      const newPath = `${path}${entry.name}`;
      if (entry.directory) {
        if (!existsSync(newPath)) {
          mkdirSync(newPath);
        }
        // recursively call this function with the new path
        console.log(`recursively calling processFiles with ${newPath}/`);
        await processFiles(`${newPath}/`);
      } else {
        // fetch the file and write it to the file system
        console.log(`writing ${newPath}`);
        const file = await fetchFile(newPath);
        writeFileSync(newPath, file);
      }
    }
  };
}

processFiles();