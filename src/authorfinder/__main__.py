"""Allow running as: python -m authorfinder"""
from .cli import main
import sys
sys.exit(main())
