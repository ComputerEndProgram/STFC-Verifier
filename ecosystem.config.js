module.exports = {
  apps: [
    {
      name: 'stfc-bot',
      script: 'bot.py',
      interpreter: '/home/ubuntu/STFC-Verifier/.venv/bin/python3',
      cwd: '/home/ubuntu/STFC-Verifier',
      env: {
        NODE_ENV: 'production'
      },
      error_file: '/home/ubuntu/STFC-Verifier/logs/error.log',
      out_file: '/home/ubuntu/STFC-Verifier/logs/out.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      restart_delay: 4000,
      max_restarts: 10,
      autorestart: true
    }
  ]
};
