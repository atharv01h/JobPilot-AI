# JobPilot AI 🚀

> A professional AI-powered desktop application that automatically discovers, tracks, and applies for software engineering and other tech jobs.

**⚠️ Disclaimer:** This project is actively under development. It is an experimental open-source tool and is not yet production-ready. There may be bugs, missing features, breaking changes, and unfinished functionality. Use at your own risk.

---

## 🌟 Features

- 🔍 **Multi-site Job Scraping:** Supports automated job discovery on LinkedIn, Naukri, Indeed, and Glassdoor.
- 🧠 **AI-Powered Automation:** Uses NVIDIA NIM (Nemotron-3-Super-120b) and Browser-Use to intelligently read and fill complex job application forms.
- 📊 **Modern Dark-Mode GUI:** Built with CustomTkinter, featuring animated stat cards, a fully interactive job table, and real-time logs.
- 🗃️ **Local Database:** Uses SQLite to track all discovered jobs, saved jobs, applied jobs, and search history—keeping your data private and local.
- 📋 **Intelligent Auto-Fill:** Upload a simple `sample_form.txt` profile, and the LLM will map your details directly into any application.
- 🔔 **Desktop Notifications:** Stay updated with native OS alerts for new job discoveries and CAPTCHA/OTP verification events.
- ⏰ **Background Scheduler:** Configure automated job sweeps to run manually, hourly, daily, or weekly.
- 📥 **CSV Export:** Easily export your entire job hunt database to CSV.

---

## 🛠️ Tech Stack

- **Language:** Python 3.11+
- **UI Framework:** CustomTkinter (Tkinter wrapper for modern UIs)
- **Browser Automation:** Playwright & Browser-Use
- **AI/LLM:** OpenAI SDK (configured for NVIDIA NIM / Anthropic / OpenAI)
- **Database:** SQLite (Async) & Pydantic for data validation

---

## 🚀 Installation & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/atharv01h/JobPilot-AI.git
cd JobPilot-AI
```

### 2. Install Dependencies
Ensure you have Python 3.11+ installed.
```bash
pip install -r requirements.txt
```

### 3. Install Playwright Browsers
```bash
playwright install chromium
```

### 4. Configuration
Copy the sample environment file and configure your API keys:
```bash
cp .env.example .env
```

Open `.env` and fill in your details. **Never commit your `.env` file to version control.**
```env
LLM_PROVIDER=nvidia
LLM_API_KEY=your_api_key_here
LLM_MODEL=nvidia/nemotron-3-super-120b-a12b

RESUME_PATH=sample_resume.pdf
FORM_PATH=sample_form.txt
```

### 5. Launch the Application
```bash
python main.py
```

---

## 📁 Folder Structure

```
JobPilot-AI/
├── main.py                  # Application entry point
├── requirements.txt         # Dependencies
├── .env                     # Local environment variables (git-ignored)
├── config/                  # Constants and settings management
├── core/                    # Database, models, and logging
├── services/                # Business logic and queue orchestration
├── automation/              # Playwright, Browser-Use, and Form Fillers
├── scrapers/                # Job board specific scraping logic
├── gui/                     # CustomTkinter UI pages and widgets
├── sample_form.txt          # Template for your profile details
└── README.md                # Documentation
```

---

## 🗺️ Roadmap

- [ ] Support for dynamic custom fields in candidate profiles.
- [ ] Improved CAPTCHA bypass methodologies.
- [ ] Direct integration with local open-source LLMs (Ollama) for privacy.
- [ ] Mac/Linux GUI stability improvements.
- [ ] Advanced analytics and conversion tracking dashboard.

---

## 🤝 Contributing

We welcome contributions from the community! If you'd like to help improve JobPilot-AI, feel free to open an Issue or submit a Pull Request. Every contribution, large or small, is appreciated.

- **Bug Reports:** Open an issue with reproduction steps.
- **Pull Requests:** Ensure code is formatted (Black/Ruff) and tests pass.
- **Feature Requests:** Share your ideas in the issues tab!

---

## 📄 License

This project is licensed under the MIT License. See the `LICENSE` file for details.
