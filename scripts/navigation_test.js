const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync("frontend/js/app.js", "utf8");

async function testUser(user) {
  const header = { innerHTML: "" };
  let redirected = null;
  const context = vm.createContext({
    console,
    Intl,
    URLSearchParams,
    FormData: class {},
    window: {
      QuorumAPI: {
        get: async () => ({ user }),
        post: async () => ({}),
      },
      location: { replace: (url) => { redirected = url; } },
    },
    document: {
      addEventListener: () => {},
      querySelector: (selector) => selector === "#topbar"
        ? header
        : { addEventListener: () => {} },
    },
  });
  vm.runInContext(source, context);
  const home = vm.runInContext("homeForUser", context)(user);
  vm.runInContext("renderHeader", context)(user);
  await vm.runInContext("landingPage", context)();
  if (!header.innerHTML.includes(`href="${home}"`)) {
    throw new Error(`Quorum link did not target ${home}`);
  }
  if (redirected !== home) {
    throw new Error(`Landing page did not redirect to ${home}`);
  }
  return home;
}

(async () => {
  const results = {
    student: await testUser({ id: 1, name: "Student", role: "student" }),
    faculty: await testUser({ id: 2, name: "Faculty", role: "faculty" }),
    admin: await testUser({
      id: 3,
      name: "Campus Admin",
      role: "admin",
      designation: "Campus Admin",
      admin_scope: "all",
    }),
  };
  console.log(JSON.stringify(results, null, 2));
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
