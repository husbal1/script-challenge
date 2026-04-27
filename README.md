# script-challenge

Create a production-ready script that will perform regular backups of a specified directory to a backup directory. The script should implement the following functionality:

Create a backup of the specified directory to a backup directory every minute.
All backups should be incremental.
Maintain the directory structure of the original directory in the backup directory.
Keep a log of each backup operation including:
Timestamp of the backup
Files that were copied
Files that were updated
Files that were deleted (if any)
 

Minimal requirements:

For each of these events, it should print a message to the screen.
The script must be portable, execute and compile (if language requires) on a vanilla Linux/Unix environment without network connectivity.
 

Important criteria that will be evaluated:

Algorithm
Portability
User friendliness
Maintainability
Readability
Scalability
Usability
Cost




I need you to act as my Lead Developer. I will provide the requirements below. When generating the solution, please:
1. Use a modular and clean code structure.
2. Include robust error handling (try-except blocks) and helpful logging/print statements.
3. Add concise comments and a brief docstring explaining how to run the script.
4. Ensure the code is 'production-ready' rather than just a quick snippet.
5. If there are multiple ways to solve it, choose the most efficient/standard approach.
6. Use only Python default/built-in libraries (no pip installs).
 

Use any of the following languages:

Go
Python
Bash




# [Project Name / Challenge Title]

## 🎯 Objective
[One sentence description of what the script does]. 
Designed for **zero-dependency environments** using only Python Standard Libraries.

## 🚀 Key Features
* **Production-Ready:** Includes robust logging and error handling.
* **Portable:** Compatible with vanilla Linux/Unix (Python 3.x).
* **Efficient:** Optimized for [Polling/Event-driven/Memory] performance.
* **SRE Mindset:** Focuses on idempotency and graceful exits.

## 🛠 Tech Stack
* **Language:** Python 3.x
* **Standard Libs used:** `os`, `sys`, `logging`, `argparse`, [Add Others Tomorrow]

## 📦 Installation & Usage
1. **Clone the repo:**
   ```bash
   git clone [https://github.com/hballout/script-challenge.git](https://github.com/hballout/script-challenge.git)
   cd script-challenge
