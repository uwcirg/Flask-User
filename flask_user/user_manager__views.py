"""This module implements UserManager view methods.
"""

# Author: Ling Thio <ling.thio@gmail.com>
# Copyright (c) 2013 Ling Thio

from datetime import datetime
from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from .decorators import login_required
from . import signals

# Python version specific imports
from sys import version_info as py_version
is_py2 = (py_version[0] == 2)     #: Python 2.x?
is_py3 = (py_version[0] == 3)     #: Python 3.x?
if is_py2:    # pragma: no cover
    from urllib import quote, unquote
if is_py3:
    from urllib.parse import quote, unquote

from .translation_utils import gettext as _    # map _() to gettext()


# This class mixes into the UserManager class.
# Mixins allow for maintaining code and docs across several files.
class UserManager__Views(object):
    """Flask-User views."""

    @login_required
    def change_password_view(self):
        """ Prompt for old password and new password and change the user's password."""
        um = current_app.user_manager
        db_adapter = um.db_adapter

        # Initialize form
        form = um.change_password_form(request.form)
        safe_next = self._get_safe_next_param('next', um.USER_AFTER_CHANGE_PASSWORD_ENDPOINT)
        form.next.data = safe_next

        # Process valid POST
        if request.method == 'POST' and form.validate():
            # Hash password
            password_hash = um.password_manager.hash_password(form.new_password.data)

            # Update user.password
            um.db_adapter.update_object(current_user, password=password_hash)
            um.db_adapter.commit()

            # Send 'password_changed' email
            if um.USER_ENABLE_EMAIL and um.USER_SEND_PASSWORD_CHANGED_EMAIL:
                um.email_manager.send_password_changed_email(current_user)

            # Send password_changed signal
            signals.user_changed_password.send(current_app._get_current_object(), user=current_user)

            # Prepare one-time system message
            flash(_('Your password has been changed successfully.'), 'success')

            # Redirect to 'next' URL
            safe_next = um.make_safe_url(form.next.data)
            return redirect(safe_next)

        # Process GET or invalid POST
        um.prepare_domain_translations()
        return render_template(um.USER_CHANGE_PASSWORD_TEMPLATE, form=form)


    @login_required
    def change_username_view(self):
        """ Prompt for new username and old password and change the user's username."""
        um = current_app.user_manager
        db_adapter = um.db_adapter

        # Initialize form
        form = um.change_username_form(request.form)
        safe_next = self._get_safe_next_param('next', um.USER_AFTER_CHANGE_USERNAME_ENDPOINT)
        form.next.data = safe_next

        # Process valid POST
        if request.method == 'POST' and form.validate():
            new_username = form.new_username.data

            # Change username
            db_adapter.update_object(current_user, username=new_username)
            db_adapter.commit()

            # Send 'username_changed' email
            if um.USER_ENABLE_EMAIL and um.USER_SEND_USERNAME_CHANGED_EMAIL:
                um.send_username_changed_email(current_user)

            # Send username_changed signal
            signals.user_changed_username.send(current_app._get_current_object(), user=current_user)

            # Prepare one-time system message
            flash(_("Your username has been changed to '%(username)s'.", username=new_username), 'success')

            # Redirect to 'next' URL
            safe_next = um.make_safe_url(form.next.data)
            return redirect(safe_next)

        # Process GET or invalid POST
        um.prepare_domain_translations()
        return render_template(um.USER_CHANGE_USERNAME_TEMPLATE, form=form)


    def confirm_email_view(self, token):
        """ Verify email confirmation token and activate the user account."""
        # Verify token
        um = current_app.user_manager
        db_adapter = um.db_adapter
        data_items = um.token_manager.verify_token(
            token,
            um.USER_CONFIRM_EMAIL_EXPIRATION)

        if not data_items:
            flash(_('Invalid confirmation token.'), 'error')
            return redirect(url_for('user.login'))

        # Confirm email by setting User.email_confirmed_at=utcnow() or UserEmail.email_confirmed_at=utcnow()
        object_id = data_items[0]
        user = None
        if um.UserEmailClass:
            user_email = um.get_user_email_by_id(object_id)
            if user_email:
                db_adapter.update_object(user_email, email_confirmed_at=datetime.utcnow())
                user = user_email.user
        else:
            user_email = None
            user = um.get_user_by_id(object_id)
            if user:
                db_adapter.update_object(user, email_confirmed_at=datetime.utcnow())

        if user:
            # If User.active exists: activate User
            if hasattr(user, 'active'):
                db_adapter.update_object(user, active=True)
        else:  # pragma: no cover
            flash(_('Invalid confirmation token.'), 'error')
            return redirect(url_for('user.login'))

        db_adapter.commit()

        # Send email_confirmed signal
        signals.user_confirmed_email.send(current_app._get_current_object(), user=user)

        # Prepare one-time system message
        flash(_('Your email has been confirmed.'), 'success')

        # Auto-login after confirm or redirect to login page
        safe_next = self._get_safe_next_param('next', um.USER_AFTER_CONFIRM_ENDPOINT)
        if um.USER_AUTO_LOGIN_AFTER_CONFIRM:
            return self._do_login_user(user, safe_next)  # auto-login
        else:
            return redirect(url_for('user.login') + '?next=' + quote(safe_next))  # redirect to login page

        pass

    @login_required
    def edit_user_profile_view(self):
        um = current_app.user_manager
        um.prepare_domain_translations()
        return render_template(um.USER_EDIT_USER_PROFILE_TEMPLATE)

    @login_required
    def email_action_view(self, id, action):
        """ Perform action 'action' on UserEmail object 'id'
        """
        um = current_app.user_manager
        db_adapter = um.db_adapter

        # Retrieve UserEmail by id
        user_email = db_adapter.find_first_object(um.UserEmailClass, id=id)

        # Users may only change their own UserEmails
        if not user_email or user_email.user_id != current_user.id:
            return self.unauthorized_view()

        if action == 'delete':
            # Primary UserEmail can not be deleted
            if user_email.is_primary:
                return self.unauthorized_view()
            # Delete UserEmail
            db_adapter.delete_object(user_email)
            db_adapter.commit()

        elif action == 'make-primary':
            # Disable previously primary emails
            user_emails = db_adapter.find_objects(um.UserEmailClass, user_id=current_user.id)
            for other_user_email in user_emails:
                if other_user_email.is_primary:
                    db_adapter.update_object(other_user_email, is_primary=False)
            # Enable current primary email
            db_adapter.update_object(user_email, is_primary=True)
            db_adapter.commit()

        elif action == 'confirm':
            self._send_confirm_email(user_email.user, user_email)

        else:
            return self.unauthorized_view()

        return redirect(url_for('user.manage_emails'))


    def forgot_password_view(self):
        """Prompt for email and send reset password email."""
        um = current_app.user_manager
        db_adapter = um.db_adapter

        # Initialize form
        form = um.forgot_password_form(request.form)

        # Process valid POST
        if request.method == 'POST' and form.validate():
            email = form.email.data
            user, user_email = um.find_user_by_email(email)

            if user:
                if user:
                    # Send forgot password email
                    um.email_manager.send_reset_password_email(user, user_email)

                    # Send forgot_password signal
                    signals.user_forgot_password.send(current_app._get_current_object(), user=user)

            # Prepare one-time system message
            flash(_(
                "A reset password email has been sent to '%(email)s'. Open that email and follow the instructions to reset your password.",
                email=email), 'success')

            # Redirect to the login page
            return redirect(self._endpoint_url(um.USER_AFTER_FORGOT_PASSWORD_ENDPOINT))

        # Process GET or invalid POST
        um.prepare_domain_translations()
        return render_template(um.USER_FORGOT_PASSWORD_TEMPLATE, form=form)

    @login_required
    def manage_emails_view(self):
        um = current_app.user_manager
        db_adapter = um.db_adapter

        user_emails = db_adapter.find_objects(um.UserEmailClass, user_id=current_user.id)
        form = um.add_email_form()

        # Process valid POST request
        if request.method == "POST" and form.validate():
            user_emails = db_adapter.add_object(um.UserEmailClass,
                                                user_id=current_user.id,
                                                email=form.email.data)
            db_adapter.commit()
            return redirect(url_for('user.manage_emails'))

        # Process GET or invalid POST request
        um.prepare_domain_translations()
        return render_template(um.USER_MANAGE_EMAILS_TEMPLATE,
                      user_emails=user_emails,
                      form=form,
                      )

    @login_required
    def invite_user_view(self):
        """ Allows users to send invitations to register an account """
        um = current_app.user_manager
        db_adapter = um.db_adapter

        invite_user_form = um.invite_user_form(request.form)

        if request.method == 'POST' and invite_user_form.validate():
            email = invite_user_form.email.data

            User = um.UserClass
            user_class_fields = User.__dict__
            user_fields = {
                "email": email
            }

            user, user_email = um.find_user_by_email(email)
            if user:
                flash("User with that email has already registered", "error")
                return redirect(url_for('user.invite_user'))
            else:
                user_invitation = db_adapter \
                    .add_object(um.UserInvitationClass, **{
                    "email": email,
                    "invited_by_user_id": current_user.id
                })
            db_adapter.commit()

            try:
                # Send 'invite' email
                um.send_invite_user_email(current_user, user_invitation)
            except Exception as e:
                # delete new User object if send fails
                db_adapter.delete_object(user_invitation)
                db_adapter.commit()
                raise

            signals \
                .user_sent_invitation \
                .send(current_app._get_current_object(), user_invitation=user_invitation,
                      form=invite_user_form)

            flash(_('Invitation has been sent.'), 'success')
            safe_next = self._get_safe_next_param('next', um.USER_AFTER_INVITE_ENDPOINT)
            return redirect(safe_next)

        um.prepare_domain_translations()
        return render_template(um.USER_INVITE_USER_TEMPLATE, form=invite_user_form)


    def login_view(self):
        """Prepare and process the login form."""

        # Authenticate username/email and login authenticated users.
        um = current_app.user_manager
        db_adapter = um.db_adapter

        safe_next = self._get_safe_next_param('next', um.USER_AFTER_LOGIN_ENDPOINT)
        safe_reg_next = self._get_safe_next_param('reg_next', um.USER_AFTER_REGISTER_ENDPOINT)

        # Immediately redirect already logged in users
        if self.call_or_get(current_user.is_authenticated) and um.USER_AUTO_LOGIN_AT_LOGIN:
            return redirect(safe_next)

        # Initialize form
        login_form = um.login_form(request.form)  # for login.html
        register_form = um.register_form()  # for login_or_register.html
        if request.method != 'POST':
            login_form.next.data = register_form.next.data = safe_next
            login_form.reg_next.data = register_form.reg_next.data = safe_reg_next

        # Process valid POST
        if request.method == 'POST' and login_form.validate():
            # Retrieve User
            user = None
            user_email = None
            if um.USER_ENABLE_USERNAME:
                # Find user record by username
                user = um.find_user_by_username(login_form.username.data)
                user_email = None
                # Find primary user_email record
                if user and um.UserEmailClass:
                    user_email = db_adapter.find_first_object(um.UserEmailClass,
                                                              user_id=user.id,
                                                              is_primary=True,
                                                              )
                # Find user record by email (with form.username)
                if not user and um.USER_ENABLE_EMAIL:
                    user, user_email = um.find_user_by_email(login_form.username.data)
            else:
                # Find user by email (with form.email)
                user, user_email = um.find_user_by_email(login_form.email.data)

            if user:
                # Log user in
                safe_next = um.make_safe_url(login_form.next.data)
                return self._do_login_user(user, safe_next, login_form.remember_me.data)

        # Process GET or invalid POST
        um.prepare_domain_translations()
        return render_template(um.USER_LOGIN_TEMPLATE,
                      form=login_form,
                      login_form=login_form,
                      register_form=register_form)

    def logout_view(self):
        """Process the logout link."""
        """ Sign the user out."""
        um = current_app.user_manager

        # Send user_logged_out signal
        signals.user_logged_out.send(current_app._get_current_object(), user=current_user)

        # Use Flask-Login to sign out user
        logout_user()

        # Prepare one-time system message
        flash(_('You have signed out successfully.'), 'success')

        # Redirect to logout_next endpoint or '/'
        safe_next = self._get_safe_next_param('next', um.USER_AFTER_LOGOUT_ENDPOINT)
        return redirect(safe_next)

    def register_view(self):
        """ Display registration form and create new User."""

        um = current_app.user_manager
        db_adapter = um.db_adapter

        safe_next = self._get_safe_next_param('next', um.USER_AFTER_LOGIN_ENDPOINT)
        safe_reg_next = self._get_safe_next_param('reg_next', um.USER_AFTER_REGISTER_ENDPOINT)

        # Initialize form
        login_form = um.login_form()  # for login_or_register.html
        register_form = um.register_form(request.form)  # for register.html

        # invite token used to determine validity of registeree
        invite_token = request.values.get("token")

        # require invite without a token should disallow the user from registering
        if um.USER_REQUIRE_INVITATION and not invite_token:
            flash("Registration is invite only", "error")
            return redirect(url_for('user.login'))

        user_invitation = None
        if invite_token and um.UserInvitationClass:
            user_invitation = db_adapter.find_first_object(um.UserInvitationClass, token=invite_token)
            if user_invitation:
                register_form.invite_token.data = invite_token
            else:
                flash("Invalid invitation token", "error")
                return redirect(url_for('user.login'))

        if request.method != 'POST':
            login_form.next.data = register_form.next.data = safe_next
            login_form.reg_next.data = register_form.reg_next.data = safe_reg_next
            if user_invitation:
                register_form.email.data = user_invitation.email

        # Process valid POST
        if request.method == 'POST' and register_form.validate():
            # Create a User object using Form fields that have a corresponding User field
            User = um.UserClass
            user_class_fields = User.__dict__
            user_fields = {}

            # Create a UserEmail object using Form fields that have a corresponding UserEmail field
            if um.UserEmailClass:
                UserEmail = um.UserEmailClass
                user_email_class_fields = UserEmail.__dict__
                user_email_fields = {}

            # If User.active exists: activate User
            if hasattr(um.UserClass, 'active'):
                user_fields['active'] = True

            # For all form fields
            for field_name, field_value in register_form.data.items():
                # Hash password field
                if field_name == 'password':
                    password_hash = um.password_manager.hash_password(field_value)
                    user_fields['password'] = password_hash
                # Store corresponding Form fields into the User object and/or UserProfile object
                else:
                    if field_name in user_class_fields:
                        user_fields[field_name] = field_value
                    if um.UserEmailClass:
                        if field_name in user_email_class_fields:
                            user_email_fields[field_name] = field_value

            # Add User record using named arguments 'user_fields'
            user = db_adapter.add_object(User, **user_fields)

            # Add UserEmail record using named arguments 'user_email_fields'
            if um.UserEmailClass:
                user_email = db_adapter.add_object(UserEmail,
                                                   user=user,
                                                   is_primary=True,
                                                   **user_email_fields)
            else:
                user_email = None

            # Email confirmation depends on the USER_ENABLE_CONFIRM_EMAIL setting
            request_email_confirmation = um.USER_ENABLE_CONFIRM_EMAIL
            # Users that register through an invitation, can skip this process
            # but only when they register with an email that matches their invitation.
            if user_invitation:
                if user_invitation.email.lower() == register_form.email.data.lower():
                    db_adapter.update_object(user, email_confirmed_at=datetime.utcnow())
                    request_email_confirmation = False

            db_adapter.commit()

            # Send 'registered' email and delete new User object if send fails
            if um.USER_SEND_REGISTERED_EMAIL:
                try:
                    # Send 'confirm email' or 'registered' email
                    self._send_registered_email(user, user_email, request_email_confirmation)
                except Exception as e:
                    # delete new User object if send  fails
                    db_adapter.delete_object(user)
                    db_adapter.commit()
                    raise

            # Send user_registered signal
            signals.user_registered.send(current_app._get_current_object(),
                                         user=user,
                                         user_invitation=user_invitation)

            # Redirect if USER_ENABLE_CONFIRM_EMAIL is set
            if um.USER_ENABLE_CONFIRM_EMAIL and request_email_confirmation:
                safe_reg_next = um.make_safe_url(register_form.reg_next.data)
                return redirect(safe_reg_next)

            # Auto-login after register or redirect to login page
            if 'reg_next' in request.args:
                safe_reg_next = um.make_safe_url(register_form.reg_next.data)
            else:
                safe_reg_next = self._endpoint_url(um.USER_AFTER_CONFIRM_ENDPOINT)
            if um.USER_AUTO_LOGIN_AFTER_REGISTER:
                return self._do_login_user(user, safe_reg_next)  # auto-login
            else:
                return redirect(url_for('user.login') + '?next=' + quote(safe_reg_next))  # redirect to login page

        # Process GET or invalid POST
        um.prepare_domain_translations()
        return render_template(um.USER_REGISTER_TEMPLATE,
                      form=register_form,
                      login_form=login_form,
                      register_form=register_form)


    def resend_email_confirmation_view(self):
        """Prompt for email and re-send email conformation email."""
        um = current_app.user_manager
        db_adapter = um.db_adapter

        # Initialize form
        form = um.resend_email_confirmation_form(request.form)

        # Process valid POST
        if request.method == 'POST' and form.validate():
            email = form.email.data

            # Find user by email
            user, user_email = um.find_user_by_email(email)
            if user:
                self._send_confirm_email(user, user_email)

            # Redirect to the login page
            return redirect(self._endpoint_url(um.USER_AFTER_RESEND_EMAIL_CONFIRMATION_ENDPOINT))

        # Process GET or invalid POST
        um.prepare_domain_translations()
        return render_template(um.USER_RESENT_CONFIRM_EMAIL_TEMPLATE, form=form)


    def reset_password_view(self, token):
        """ Verify the password reset token, Prompt for new password, and set the user's password."""
        # Verify token
        um = current_app.user_manager
        db_adapter = um.db_adapter

        if self.call_or_get(current_user.is_authenticated):
            logout_user()

        data_items = um.token_manager.verify_token(
            token,
            um.USER_RESET_PASSWORD_EXPIRATION)

        if not data_items:
            flash(_('Your reset password token is invalid.'), 'error')
            return redirect(self._endpoint_url('user.login'))

        # Get User by user ID
        user_id = data_items[0]
        user = um.get_user_by_id(user_id)

        # Mark email as confirmed
        user_email = um.get_primary_user_email(user)
        user_email.email_confirmed_at = datetime.utcnow()

        # Initialize form
        form = um.reset_password_form(request.form)

        # Process valid POST
        if request.method == 'POST' and form.validate():
            # Change password
            password_hash = um.password_manager.hash_password(form.new_password.data)
            db_adapter.update_object(user, password=password_hash)
            db_adapter.commit()

            # Send 'password_changed' email
            if um.USER_ENABLE_EMAIL and um.USER_SEND_PASSWORD_CHANGED_EMAIL:
                um.email_manager.send_password_changed_email(user)

            # Prepare one-time system message
            flash(_("Your password has been reset successfully."), 'success')

            # Auto-login after reset password or redirect to login page
            safe_next = self._get_safe_next_param('next', um.USER_AFTER_RESET_PASSWORD_ENDPOINT)
            if um.USER_AUTO_LOGIN_AFTER_RESET_PASSWORD:
                return self._do_login_user(user, safe_next)  # auto-login
            else:
                return redirect(url_for('user.login') + '?next=' + quote(safe_next))  # redirect to login page

        # Process GET or invalid POST
        um.prepare_domain_translations()
        return render_template(um.USER_RESET_PASSWORD_TEMPLATE, form=form)

    def unauthenticated_view(self):
        """ Prepare a Flash message and redirect to USER_UNAUTHENTICATED_ENDPOINT"""
        um = current_app.user_manager
        # Prepare Flash message
        url = request.url
        flash(_("You must be signed in to access '%(url)s'.", url=url), 'error')

        # Redirect to USER_UNAUTHENTICATED_ENDPOINT
        safe_next = um.make_safe_url(url)
        return redirect(self._endpoint_url(um.USER_UNAUTHENTICATED_ENDPOINT)+'?next='+quote(safe_next))


    def unauthorized_view(self):
        """ Prepare a Flash message and redirect to USER_UNAUTHORIZED_ENDPOINT"""
        # Prepare Flash message
        url = request.script_root + request.path
        flash(_("You do not have permission to access '%(url)s'.", url=url), 'error')

        # Redirect to USER_UNAUTHORIZED_ENDPOINT
        um = current_app.user_manager
        return redirect(self._endpoint_url(um.USER_UNAUTHORIZED_ENDPOINT))

    def unconfirmed_email_view(self):
        """ Prepare a Flash message and redirect to USER_UNCONFIRMED_ENDPOINT"""
        # Prepare Flash message
        url = request.script_root + request.path
        flash(_("You must confirm your email to access '%(url)s'.", url=url), 'error')

        # Redirect to USER_UNCONFIRMED_EMAIL_ENDPOINT
        um = current_app.user_manager
        return redirect(self._endpoint_url(um.USER_UNCONFIRMED_EMAIL_ENDPOINT))


    def _send_registered_email(self, user, user_email, request_email_confirmation):
        um =  current_app.user_manager

        if um.USER_ENABLE_EMAIL and um.USER_SEND_REGISTERED_EMAIL:

            # Send 'registered' email, with or without a confirmation request
            um.email_manager.send_registered_email(user, user_email, request_email_confirmation)

            # Prepare one-time system message
            if request_email_confirmation:
                email = user_email.email if user_email else user.email
                flash(_('A confirmation email has been sent to %(email)s with instructions to complete your registration.', email=email), 'success')
            else:
                flash(_('You have registered successfully.'), 'success')


    def _send_confirm_email(self, user, user_email):
        um =  current_app.user_manager

        # Send 'confirm_email' or 'registered' email
        if um.USER_ENABLE_EMAIL and um.USER_ENABLE_CONFIRM_EMAIL:
            # Send email
            um.email_manager.send_confirm_email_email(user, user_email)

            # Prepare one-time system message
            email = user_email.email if user_email else user.email
            flash(_('A confirmation email has been sent to %(email)s with instructions to complete your registration.', email=email), 'success')


    def _do_login_user(self, user, safe_next, remember_me=False):
        # User must have been authenticated
        if not user: return self.unauthenticated()

        # Check if user account has been disabled
        if not self.call_or_get(user.is_active):
            flash(_('Your account has not been enabled.'), 'error')
            return redirect(url_for('user.login'))

        # Check if user has a confirmed email address
        um = current_app.user_manager
        if um.USER_ENABLE_EMAIL \
                and um.USER_ENABLE_CONFIRM_EMAIL \
                and not current_app.user_manager.USER_ALLOW_LOGIN_WITHOUT_CONFIRMED_EMAIL \
                and not self.user_has_confirmed_email(user):
            url = url_for('user.resend_email_confirmation')
            flash(_('Your email address has not yet been confirmed. Check your email Inbox and Spam folders for the confirmation email or <a href="%(url)s">Re-send confirmation email</a>.', url=url), 'error')
            return redirect(url_for('user.login'))

        # Use Flask-Login to sign in user
        # print('login_user: remember_me=', remember_me)
        login_user(user, remember=remember_me)

        # Send user_logged_in signal
        signals.user_logged_in.send(current_app._get_current_object(), user=user)

        # Prepare one-time system message
        flash(_('You have signed in successfully.'), 'success')

        # Redirect to 'next' URL
        return redirect(safe_next)


    # 'next' and 'reg_next' query parameters contain quoted (URL-encoded) URLs
    # that may contain unsafe hostnames.
    # Return the query parameter as a safe, unquoted URL
    def _get_safe_next_param(self, param_name, default_endpoint):
        if param_name in request.args:
            # return safe unquoted query parameter value
            safe_next = current_app.user_manager.make_safe_url(unquote(request.args[param_name]))
        else:
            # return URL of default endpoint
            safe_next = self._endpoint_url(default_endpoint)
        return safe_next


    def _endpoint_url(self, endpoint):
        return url_for(endpoint) if endpoint else '/'

