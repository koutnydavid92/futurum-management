#!/bin/bash
cd "/Users/david/Documents/Dokumenty – David – MacBook Air/Mlyko/Marketing Therapy/Futurum/Management system"
/Users/david/Library/Python/3.9/bin/streamlit run app.py --server.headless true --server.port "${PORT:-8501}"
