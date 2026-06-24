"""
Convenience launcher — run this from the project root:

    python run.py

Or launch Streamlit directly (preferred):

    streamlit run frontend/app.py        # uses backend/ package
    streamlit run streamlit_app.py       # legacy root-level entrypoint
"""
import subprocess
import sys
import os

if __name__ == "__main__":
    project_root = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_root)
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", "frontend/app.py"],
        check=True,
    )
