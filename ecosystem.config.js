// PM2-конфиг для запуска Python-бота МОЛВИ.
// Альтернатива systemd — используйте, если на сервере уже стоит Node.js + PM2.
//
// Запуск:
//   pm2 start ecosystem.config.js
//   pm2 save
//   pm2 startup        # выполните выведенную команду, чтобы PM2 поднимался после ребута
//
// Путь к интерпретатору venv должен существовать на сервере.
module.exports = {
  apps: [
    {
      name: "molvi-bot",
      // Запускаем модуль `bot` (python -m bot) через интерпретатор venv:
      script: "-m",
      args: "bot",
      interpreter: "./.venv/bin/python",
      cwd: "/home/molvi/molvi-bot",
      autorestart: true,
      restart_delay: 5000,
      max_restarts: 50,
      // .env читается самим приложением (pydantic-settings).
      out_file: "./logs/pm2-out.log",
      error_file: "./logs/pm2-err.log",
    },
  ],
};
