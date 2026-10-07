const fs = require('fs');
const path = require('path');

const target = path.resolve(__dirname, '..', 'node_modules', 'v-code-diff', 'package.json');

if (!fs.existsSync(target)) {
  console.error(
    '[v-code-diff] missing dependency.\n' +
      '  npm install did not place v-code-diff under node_modules.\n' +
      '  Fix: cd main/manager-web && npm install v-code-diff@^1.16.0\n' +
      '  Ref: https://github.com/xinnan-tech/xiaozhi-esp32-server/issues/3389'
  );
  process.exit(1);
}
