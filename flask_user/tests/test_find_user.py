"""
    tests.test_find_user.py
    ---------------------------
    Flask-User automated tests:
    Test finding user functionality

    :copyright: (c) 2013 by Ling Thio
    :author: Ling Thio (ling.thio@gmail.com)
    :license: Simplified BSD License, see LICENSE.txt for more details.
"""

from __future__ import print_function
import datetime

from flask import current_app

# **********************
# ** Global Variables **
# **********************
user0 = None

# ********************************
# ** Automatically called Tests **
# ********************************
# The 'client' and 'app' parameters are set up in conftest.py
# Functions that start with 'test' will be run automatically by the test suite runner (py.test)

def test_init(db):
    """
    Setup a test user
    """
    global user0

    um = current_app.user_manager
    hashed_password = um.hash_password('Password1')
    User = um.db_adapter.UserClass

    user0 = User(username='user0', email='user0@example.com', password=hashed_password, active=True)
    db.session.add(user0)
    db.session.commit()

def test_find_user_by_email(app, db, client):
    """
    Test 'find_user_by_email' feature
    """
    global user0
    um = current_app.user_manager

    # Find the user by their email
    found_user = um.find_user_by_email(user0.email)[0]
    assert found_user is not None
    assert found_user.id == user0.id

    # Verify user not found when wildcard used
    found_user = um.find_user_by_email('user_@example.com')[0]
    assert found_user is None

def test_find_user_by_username(app, db, client):
    """
    Test 'find_user_by_email' feature
    """
    global user0
    um = current_app.user_manager

    # Find the user by their username
    found_user = um.find_user_by_username(user0.username)
    assert found_user is not None
    assert found_user.id == user0.id

    # Verify user not found when wildcard used
    found_user = um.find_user_by_username('user_')
    assert found_user is None

def test_cleanup(db):
    """
    Delete user0
    """
    global user0
    db.session.delete(user0)
    db.session.commit()
    user0 = None
