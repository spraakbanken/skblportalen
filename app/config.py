# Statement for enabling the development environment
DEBUG = True

# Define the application directory
import os
BASE_DIR = os.path.abspath(os.path.dirname(__file__))  

LANGUAGES = {
    'en': 'English',
    'sv': 'Swedish'
}

BABEL_DEFAULT_LOCALE = 'en'

KARP_BACKEND = "https://ws.spraakbanken.gu.se/ws/swo"
KARP_AUTH_HASH = "trustno1"

# Application threads. A common general assumption is
# using 2 per available processor cores - to handle
# incoming requests using one and performing background
# operations using the other.
THREADS_PER_PAGE = 2

# Enable protection agains *Cross-site Request Forgery (CSRF)*
CSRF_ENABLED     = True

# Use a secure, unique and absolutely secret key for
# signing the data. 
CSRF_SESSION_KEY = "secret"

# Secret key for signing cookies
SECRET_KEY = "secret"