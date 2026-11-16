const installed = require('/fetch-shim.cjs').installFetchShim();
if (!process.env.HARMONY_PROOT_MANAGED_SHELL) console.log('PHONE_FETCH_SHIM', installed);
