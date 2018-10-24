from app.core.models.form import FormMeta, Item
from flask_login import current_user
from datetime import datetime
from app.utils.url_condition.url_condition_mongodb import *
from app.utils.Error import CustomError


def find_form_meta(name, version=None):
    from app.utils.mongodb import mongo
    if name is None:
        return None, CustomError(500, 200, 'name must be given')
    if version is None:
        condition = {'using': True, 'name': name}
        try:
            data = mongo.db.form_meta.find_one(condition)
        except Exception as e:
            return None, CustomError(500, 500, str(e))
        if data is None:
            return None, CustomError(404, 404, 'form meta not found')
        return data, None
    condition = {'name': name, 'version': version}
    try:
        data = mongo.db.form_meta.find_one(condition)
    except Exception as e:
        return None, CustomError(500, 500, str(e))
    if data is None:
        return None, CustomError(404, 404, 'form meta not found')
    return data, None


def find_form_metas(condition=None):
    from app.utils.mongodb import mongo
    url_condition = UrlCondition(condition)
    if url_condition.filter_dict is None:
        datas = mongo.db.form_meta.find()
        return datas, datas.count(), None
    if '_id' in url_condition.filter_dict:
        url_condition.filter_dict['_id']['$in'] = [ObjectId(item) for item in url_condition.filter_dict['_id']['$in']]
    try:
        datas = mongo.db.form_meta.find(url_condition.filter_dict)
    except Exception as e:
        return None, CustomError(500, 500, str(e))
    datas = sort_limit(datas, url_condition.sort_limit_dict)
    paginate = Paginate(datas, url_condition.page_dict)
    datas = paginate.data_page
    return datas, paginate.total, None


# 传入字典型返回筛选过的数据的cursor, 遍历cursor得到的是字典


def insert_form_meta(form_meta):
    from app.utils.mongodb import mongo
    form_meta.items_to_dict()
    try:
        mongo.db.form_meta.insert(form_meta.model)
    except Exception as e:
        return False, CustomError(500, 500, str(e))
    return True, None


# 传入一个FormMeta对象，存入数据库


def delete_form_meta(condition=None):
    from app.utils.mongodb import mongo
    if condition is None:
        return False, CustomError(500, 500, 'condition can not be empty')
    condition['using'] = True
    try:
        mongo.db.form_meta.update(condition, {"$set": {"using": False}})
    except Exception as e:
        return False, CustomError(500, 500, str(e))
    return True, None


# 传入一个用于匹配的字典，更改匹配到的所有文档的using值


def request_to_class(json_request):
    form_meta = FormMeta()
    meta = json_request.get('meta', dict())
    meta.update({"created_by": current_user.username,
                 "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
    name = json_request.get('name', None)
    version = json_request.get('version', None)
    form_meta.name = name
    form_meta.version = version
    form_meta.meta = meta
    item_datas = json_request.get('items', {})
    if item_datas is not None:
        for item_data in item_datas:
            item = Item()
            for k, v in item_data.items():
                item.model[k] = v
            form_meta.items.append(item)
    return form_meta


# 传入request.json字典,返回一个FormMeta对象


def to_json_dict(form_meta):
    try:
        json_dict = {
            '_id': str(form_meta.get('_id', None)),
            'meta': form_meta.get('name', None),
            'name': form_meta.get('version', None),
            'version': form_meta.get('meta', {}),
        }
    except Exception as e:
        return None, CustomError(500, 500, str(e))
    return json_dict, None