import app.core.dao as dao
from app.utils import CustomError, db, args_to_dict
from app.utils.kafka import send_kafka_message
from flask_login import current_user
from werkzeug.security import generate_password_hash, check_password_hash
import app.core.services as service
from functools import wraps
from flask import request
from flask import jsonify


class SchoolTerm():
    def __init__(self, term_name: str = None):
        self.term_name = term_name

    def __add__(self, other):
        term_parts = self.term_name.split('-')
        term_future = 2 if (int(term_parts[2]) + other) % 2 == 0 else 1
        years = other / 2 if (int(term_parts[2]) == 1) else other / 2 + 1
        begin_year = int(int(term_parts[0]) + years)
        end_year = int(int(term_parts[1]) + years)
        return SchoolTerm(term_name='-'.join([str(begin_year), str(end_year), str(term_future)]))


class AuthController():
    @classmethod
    def login(cls, username: str, password: str):
        if username is None or password is None:
            raise CustomError(403, 403, '用户名或密码错误')
        try:
            dao.User.login(username=username, password=password)
        except Exception as e:
            if isinstance(e, CustomError):
                raise e
            else:
                raise CustomError(500, 500, err_info=str(e))
        return True

    @classmethod
    def logout(cls):
        try:
            dao.User.logout()
        except Exception as e:
            raise CustomError(500, 500, e)

    @classmethod
    def get_current_user(cls):
        user = UserController.get_user(query_dict={'username': current_user.username})
        return user


class UserController():

    @classmethod
    def role_list(cls, user: dict, term: str):
        role_list_dict = {'is_grouper': '小组长', 'is_main_grouper': '大组长', 'is_admin': '管理员', 'is_leader': '学院领导',
                          'is_guider': '督导'}
        role_names = ['教师']
        for role_name_e, role_name_c in role_list_dict.items():
            if user.get(role_name_e, False):
                role_names.append(role_name_c)
        if user['is_guider']:
            supervisor = dao.Supervisor.get_supervisor(query_dict={'username': user['username'], 'term': term})
            if supervisor:
                for role_name_e, role_name_c in role_list_dict.items():
                    if supervisor.get(role_name_e, False):
                        role_names.append(role_name_c)
        return role_names

    @classmethod
    def formatter(cls, user: dict):
        term = service.TermService.get_now_term()['name']
        role_names = cls.role_list(user, term)
        user['role_names'] = role_names
        if user['is_guider']:
            supervisor = dao.Supervisor.get_supervisor(query_dict={'username': user['username'], 'term': term})
            user['guider'] = supervisor
        return user

    @classmethod
    def reformatter(cls, data: dict):
        return data

    @classmethod
    def query_users(cls, query_dict: dict = None, unscoped=False):
        if query_dict is None:
            query_dict = dict()
        (users, num) = dao.User.query_users(query_dict=query_dict, unscoped=unscoped)
        return [cls.formatter(user) for user in users], num

    @classmethod
    def get_user(cls, query_dict, unscoped=False):
        user = dao.User.get_user(query_dict=query_dict, unscoped=unscoped)
        return cls.formatter(user)

    @classmethod
    def insert_user(cls, ctx: bool = True, data: dict = None, default_password='bjfu123456'):
        if data is None:
            data = dict()
        data = cls.reformatter(data)
        username = data.get('username', None)
        if username is None:
            raise CustomError(500, 200, 'username should be given')
        try:
            dao.User.get_user(query_dict={'username': username})
        except CustomError as e:
            if e is not None:
                raise CustomError(500, 200, 'username has been used')
            elif e is not None and e.status_code != 404:
                raise e
        try:
            if data.get('password', None) is not None:
                data['password'] = default_password
            dao.User.insert_user(ctx=ctx, data=data)
            if ctx:
                db.session.commit()
        except Exception as e:
            if ctx:
                db.session.rollback()
            if isinstance(e, CustomError):
                raise e
            else:
                raise CustomError(500, 500, str(e))
        role_names = data.get('role_names', [])
        if '督导' in role_names:
            send_kafka_message(topic='user_service',
                               method='add_supervisor',
                               usernames=[username])
        return True

    @classmethod
    def update_user(cls, ctx: bool = True, username: str = '', data: dict = None):
        if data is None:
            data = dict()
        try:
            data['term'] = data.get('term', service.TermService.get_now_term()['name'])
            if username is None:
                raise CustomError(500, 500, 'username or role_names should be given')

            term = data['term']
            user = dao.User.get_user(query_dict={'username': username}, unscoped=False)
            if user is None:
                raise CustomError(404, 404, 'user is not found')
            dao.User.update_user(ctx=False, username=username, data=data)

            # supervisor role_name 变更
            role_names = list(set(data.get('role_names', [])))
            old_role_names = cls.role_list(user=user, term=term)
            new_role_names = list(set(role_names) - set(old_role_names))
            del_role_names = list(set(old_role_names) - set(role_names))
            if '督导' in del_role_names:
                del_role_names.remove('督导')
                SupervisorController.delete_supervisor(ctx=False, username=username, term=term)
            elif '督导' in new_role_names:
                new_role_names.remove('督导')
                SupervisorController.insert_supervisor(ctx=False, data=data)
            if '小组长' in del_role_names:
                del_role_names.remove('小组长')
                supervisor = dao.Supervisor.get_supervisor(query_dict={'username': username, 'term': term})
                group_name = data['group_name'] if 'group_name' in data else supervisor['group_name']
                SupervisorController.update_grouper(ctx=False, username=username, term=term,
                                                    group_name=group_name, role_name='grouper', add=False)
            elif '小组长' in new_role_names:
                new_role_names.remove('小组长')
                supervisor = dao.Supervisor.get_supervisor(query_dict={'username': username, 'term': term})
                group_name = data.get('group_name', supervisor['group_name'])
                (groupers, num) = dao.Supervisor.query_supervisors(
                    query_dict={'term_gte': [term], 'grouper': [True], 'group_name': [group_name]})
                if num > 0:
                    grouper = groupers[0]
                    SupervisorController.update_grouper(ctx=False, username=grouper['username'], term=term,
                                                        group_name=group_name, role_name='grouper', add=False)
                SupervisorController.update_grouper(ctx=False, username=username, term=term, group_name=group_name,
                                                    role_name='grouper', add=True)
            if '大组长' in del_role_names:
                del_role_names.remove('大组长')
                SupervisorController.update_grouper(ctx=False, username=username, term=term, role_name='main_grouper',
                                                    add=False)
            elif '大组长' in new_role_names:
                new_role_names.remove('大组长')
                (groupers, num) = dao.Supervisor.query_supervisors(
                    query_dict={'term_gte': [term], 'main_grouper': [True]})
                if num > 0:
                    grouper = groupers[0]
                    SupervisorController.update_grouper(ctx=False, username=grouper['username'], term=term,
                                                        role_name='main_grouper', add=False)
                SupervisorController.update_grouper(ctx=False, username=username, term=term, role_name='main_grouper',
                                                    add=True)
            if ctx:
                db.session.commit()
        except Exception as e:
            if ctx:
                db.session.rollback()
            if isinstance(e, CustomError):
                raise e
            else:
                raise CustomError(500, 500, err_info=str(e))
        return True



    @classmethod
    def delete_user(cls, ctx: bool = True, username: str = ''):
        user = dao.User.get_user(query_dict={'username': username}, unscoped=False)
        if user is None:
            raise CustomError(404, 404, '用户未找到')
        try:
            dao.User.delete_user(ctx=ctx, username=username)
            if ctx:
                db.session.commit()
        except Exception as e:
            if ctx:
                db.session.rollback()
            if isinstance(e, CustomError):
                raise e
            else:
                raise CustomError(500, 500, str(e))
        return True

    @classmethod
    def change_user_password(cls, username, password):
        user = dao.User.get_user(query_dict={'username': username}, unscoped=False)
        if user is None:
            raise CustomError(404, 404, '用户未找到')
        dao.User.update_user(ctx=False, username=username, data={
            'password_hash': generate_password_hash(password=password)
        })
        return True



class SupervisorController():
    @classmethod
    def get_supervisor_by_username(cls, query_dict: dict, unscoped: bool = False):
        term = service.TermService.get_now_term()
        query_dict.update({'term': term.get('name')})
        supervisor = dao.Supervisor.get_supervisor(query_dict=query_dict)
        user = dao.User.get_user(query_dict={'username': supervisor['username']}, unscoped=unscoped)
        supervisor['user'] = user
        return supervisor

    @classmethod
    def get_supervisor(cls, query_dict: dict, unscoped: bool = False):
        supervisor = dao.Supervisor.get_supervisor_by_id(query_dict=query_dict)
        user = dao.User.get_user(query_dict={'username': supervisor['username']}, unscoped=unscoped)
        supervisor['user'] = user
        return supervisor

    @classmethod
    def query_supervisors(cls, query_dict: dict = None, unscoped: bool = False):
        if query_dict is None:
            query_dict = dict()
        (supervisors, num) = dao.Supervisor.query_supervisors(query_dict=query_dict, unscoped=unscoped)
        for supervisor in supervisors:
            username = supervisor.get("username")
            user = dao.User.get_user(query_dict={'username': username}, unscoped=False)
            supervisor['user'] = user
        return supervisors, num

    @classmethod
    def update_supervisor(cls, id: int, ctx: bool = True, data: dict = None):
        if data is None:
            data = dict()
        term = data.get('term', service.TermService.get_now_term()['name'])
        supervisor = dao.Supervisor.get_supervisor_by_id(query_dict={'id': id})
        username = supervisor['username']
        group = data.get('group_name', supervisor['group_name'])
        grouper = supervisor.get('is_grouper')
        main_grouper = supervisor.get('is_main_grouper')
        is_grouper = data.get('is_grouper', False)
        is_main_grouper = data.get('is_main_grouper', False)
        try:
            if grouper and not is_grouper:
                cls.update_grouper(ctx=False, username=username, term=term, group_name=group, role_name='grouper',
                                   add=False)
            if not grouper and is_grouper:
                (groupers, num) = dao.Supervisor.query_supervisors(
                    query_dict={'term_gte': [term], 'grouper': [True], 'group_name': [group]})
                if num > 0:
                    grouper = groupers[0]
                    cls.update_grouper(ctx=False, username=grouper['username'], term=term, group_name=group,
                                       role_name='grouper', add=False)
                cls.update_grouper(ctx=False, username=username, term=term, group_name=group, role_name='grouper',
                                   add=True)
            if main_grouper and not is_main_grouper:
                cls.update_grouper(ctx=False, username=username, term=term, role_name='main_grouper', add=False)
            if not main_grouper and is_main_grouper:
                (groupers, num) = dao.Supervisor.query_supervisors(
                    query_dict={'term_gte': [term], 'main_grouper': [True]})
                if num > 0:
                    grouper = groupers[0]
                    cls.update_grouper(ctx=False, username=grouper['username'], term=term, role_name='main_grouper',
                                       add=False)
                cls.update_grouper(ctx=False, username=username, term=term, role_name='main_grouper',
                                   add=True)
            dao.Supervisor.update_supervisor(query_dict={'id': [id]}, data=data)
            if ctx:
                db.session.commit()
        except Exception as e:
            if ctx:
                db.session.rollback()
            if isinstance(e, CustomError):
                raise e
            else:
                raise CustomError(500, 500, str(e))
        return True

    @classmethod
    def query_supervisors_expire(cls, query_dict: dict = None, unscoped: bool = False):
        if query_dict is None:
            query_dict = dict()
        term = query_dict.get('term', [])
        if len(term) == 0:
            term = [service.TermService.get_now_term()['name']]
        if 'term' in query_dict:
            del query_dict['term']
        new_term = [(SchoolTerm(term[0]) + 1).term_name]

        all_query_dict = query_dict
        all_query_dict['term'] = term
        all_usernames = list()
        (all_supervisors, num) = dao.Supervisor.query_supervisors(query_dict=all_query_dict, unscoped=unscoped)
        for supervisor in all_supervisors:
            all_usernames.append(supervisor['username'])

        can_query_dict = query_dict
        can_query_dict['term'] = new_term
        can_usernames = list()
        (can_supervisors, num) = dao.Supervisor.query_supervisors(query_dict=can_query_dict, unscoped=unscoped)
        for supervisor in can_supervisors:
            can_usernames.append(supervisor['username'])

        expire_usernames = list(set(all_usernames) - set(can_usernames))
        query_dict['username'] = expire_usernames
        (supervisors, num) = dao.Supervisor.query_supervisors(query_dict=query_dict, unscoped=False)
        for supervisor in supervisors:
            username = supervisor.get('username')
            user = dao.User.get_user(query_dict={'username': username}, unscoped=False)
            supervisor['user'] = user
        return supervisors, num

    @classmethod
    def delete_supervisor(cls, ctx: bool = True, username: str = '', term: str = None):
        if term is None:
            term = service.TermService.get_now_term()['name']
        user = dao.User.get_user(query_dict={'username': username}, unscoped=False)
        if user is None:
            raise CustomError(404, 404, 'user is not found')
        try:
            dao.User.update_user(ctx=False, username=username, data={'guider': False})
            dao.Supervisor.delete_supervisor(ctx=False, query_dict={'username': [username], 'term_gte': [term]})
            if ctx:
                db.session.commit()
        except Exception as e:
            if ctx:
                db.session.rollback()
            if isinstance(e, CustomError):
                raise e
            else:
                raise CustomError(500, 500, str(e))
        return True

    @classmethod
    def insert_supervisor(cls, ctx: bool = True, data: dict = None):
        if data is None:
            data = dict()
        username = data.get('username', None)
        user = dao.User.get_user(query_dict={'username': username}, unscoped=False)
        if user is None:
            raise CustomError(404, 404, 'user is not found')
        term = data.get('term', service.TermService.get_now_term()['name'])
        data['name'] = user['name']
        (_, num) = dao.Supervisor.query_supervisors(query_dict={'username': [username], 'term': [term]}, unscoped=False)
        if num != 0:
            raise CustomError(500, 200, 'user has been supervisor')
        if username is None:
            raise CustomError(500, 200, 'username should be given')
        if term is None:
            term = service.TermService.get_now_term()['name']
        try:
            grouper = data.get('is_grouper', False)
            main_grouper = data.get('is_main_grouper', False)
            if grouper:
                dao.Supervisor.update_supervisor(
                    query_dict={'group_name': [data.get('group_name')], 'term_gte': [term], 'grouper': [True]},
                    data={'grouper': False})
            if main_grouper:
                dao.Supervisor.update_supervisor(
                    query_dict={'term_gte': [term], 'main_grouper': [True]},
                    data={'main_grouper': False})
            dao.User.update_user(ctx=False, username=username, data={'guider': True})
            school_term = SchoolTerm(term)
            data['grouper'] = grouper
            data['main_grouper'] = main_grouper
            for i in range(0, 4):
                data['term'] = school_term.term_name
                (_, num) = dao.Term.query_terms(query_dict={'name': [school_term.term_name]})
                if num == 0:
                    dao.Term.insert_term(ctx=False, data={'name': school_term.term_name})
                dao.Supervisor.insert_supervisor(ctx=False, data=data)
                school_term = school_term + 1
                lesson_record_data = {'username': username, 'term': school_term.term_name, 'group_name': data['group_name'],
                                      'name': user['name']}
                dao.LessonRecord.insert_lesson_record(ctx=False, data=lesson_record_data)
            if ctx:
                db.session.commit()
        except Exception as e:
            if ctx:
                db.session.rollback()
            if isinstance(e, CustomError):
                raise e
            else:
                raise CustomError(500, 500, err_info=str(e))
        return True

    @classmethod
    def update_grouper(cls, ctx: bool = True, username: str = None, term: str = None, group_name: str = None,
                       role_name: str = None, add: bool = False):
        (supervisors, num) = dao.Supervisor.query_supervisors(query_dict={'username': [username], 'term_gte': [term]})
        if num == 0:
            raise CustomError(500, 200, 'user must be supervisor')
        try:
            if group_name is None:
                dao.Supervisor.update_supervisor(ctx=False, query_dict={'username': [username], 'term_gte': [term]},
                                                 data={role_name: add})
            else:
                dao.Supervisor.update_supervisor(ctx=False, query_dict={'username': [username], 'term_gte': [term]},
                                                 data={role_name: add, 'group_name': group_name})
            if add:
                dao.Group.update_group(ctx=False, query_dict={'name': [group_name]}, data={'leader_name': [username]})
            else:
                dao.Group.update_group(ctx=False, query_dict={'name': [group_name]}, data={'leader_name': ['']})
            if ctx:
                db.session.commit()
        except Exception as e:
            if ctx:
                db.session.rollback()
            if isinstance(e, CustomError):
                raise e
            else:
                raise CustomError(500, 500, err_info=str(e))
        return True

    @classmethod
    def batch_renewal(cls, ctx: bool = True, data: dict = None):
        if data is None:
            data = dict()
        usernames = data.get('usernames', None)
        term = data.get('term', None)
        if usernames is None:
            raise CustomError(500, 500, 'usernames should be given')
        if term is None:
            term = service.TermService.get_now_term()['name']
        try:
            for username in usernames:
                user = dao.User.get_user(query_dict={'username': username})
                school_term = SchoolTerm(term)
                supervisor = dao.Supervisor.get_supervisor(query_dict={'username': username, 'term': term})
                for i in range(0, 4):
                    school_term = school_term + 1
                    data['term'] = school_term.term_name
                    (_, num) = dao.Term.query_terms(query_dict={'name': [school_term.term_name]})
                    if num == 0:
                        dao.Term.insert_term(ctx=False, data={'name': school_term.term_name})
                    (_, num) = dao.Supervisor.query_supervisors(
                        query_dict={'username': username, 'term': [data['term']]},
                        unscoped=False)
                    if num != 0:
                        continue
                    data['username'] = username
                    data['group_name'] = supervisor['group_name']
                    data['name'] = user['name']
                    dao.Supervisor.insert_supervisor(ctx=False, data=data)
            if ctx:
                db.session.commit()
        except Exception as e:
            if ctx:
                db.session.rollback()
            if isinstance(e, CustomError):
                raise e
            else:
                raise CustomError(500, 500, str(e))
        return True

    @classmethod
    def get_supervisor_num(cls, query_dict: dict = None):
        if query_dict is None:
            query_dict = dict()
        term = query_dict.get('term', service.TermService.get_now_term()['name'])
        num = dao.Supervisor.count(query_dict={'term': [term]})
        return num


class GroupController():
    @classmethod
    def formatter(cls, group: dict):
        leader = dao.User.get_user({'username':group['leader_name']}, unscoped=True)
        return {'group_name': group['group_name'], 'leader': leader}

    @classmethod
    def query_groups(cls, query_dict):
        groups, num = dao.Group.query_groups(query_dict)
        return [cls.formatter(group) for group in groups], num

