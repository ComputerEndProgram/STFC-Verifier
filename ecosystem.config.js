module.exports = {
  apps: [
    {
      name: "verifier",
      script: "/home/ubuntu/.local/bin/verifier",
      cwd: "/home/ubuntu/Merged-Verifier",
      interpreter: "/usr/bin/python3.13",
    },
    {
      name: "verifier-admin-web",
      script: "/usr/bin/python3.13",
      args: "-m admin_web",
      cwd: "/home/ubuntu/Merged-Verifier",
    },
  ],
};
