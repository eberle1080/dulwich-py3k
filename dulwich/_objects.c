/*
 * Copyright (C) 2009 Jelmer Vernooij <jelmer@samba.org>
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; version 2
 * of the License or (at your option) a later version of the License.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
 * MA  02110-1301, USA.
 */

#include <Python.h>
#include <stdlib.h>
#include <sys/stat.h>

#if defined(__MINGW32_VERSION) || defined(__APPLE__)
size_t rep_strnlen(char *text, size_t maxlen);
size_t rep_strnlen(char *text, size_t maxlen)
{
	const char *last = memchr(text, '\0', maxlen);
	return last ? (size_t) (last - text) : maxlen;
}
#define strnlen rep_strnlen
#endif

#define bytehex(x) (((x)<0xa)?('0'+(x)):('a'-0xa+(x)))

static PyObject *tree_entry_cls, *Sha1Sum;
static PyObject *object_format_exception_cls;


static PyObject *bytes_to_pysha(const unsigned char *sha) {
    PyObject* bytes = PyBytes_FromStringAndSize(sha, 20);
    if(bytes == NULL) {
        ///
    }

    PyObject* pysha = PyObject_CallFunctionObjArgs(Sha1Sum, bytes);
    Py_DECREF(bytes);

    if(pysha == NULL) {
        ///
    }

    return pysha;
}

static PyObject *py_parse_tree(PyObject *self, PyObject *args, PyObject *kw)
{
	char *text, *start, *end;
	int len, namelen, strict;
	PyObject *ret, *item, *name, *py_strict = NULL, *sha;
	static char *kwlist[] = {"text", "strict", NULL};

	if (!PyArg_ParseTupleAndKeywords(args, kw, "s#|O", kwlist,
	                                 &text, &len, &py_strict))
		return NULL;


	strict = py_strict ?  PyObject_IsTrue(py_strict) : 0;

	/* TODO: currently this returns a list; if memory usage is a concern,
	 * consider rewriting as a custom iterator object */
	ret = PyList_New(0);

	if (ret == NULL) {
		return NULL;
	}

	start = text;
	end = text + len;

	while (text < end) {
		long mode;
		if (strict && text[0] == '0') {
			PyErr_SetString(object_format_exception_cls,
			                "Illegal leading zero on mode");
			Py_DECREF(ret);
			return NULL;
		}

		mode = strtol(text, &text, 8);

		if (*text != ' ') {
			PyErr_SetString(PyExc_ValueError, "Expected space");
			Py_DECREF(ret);
			return NULL;
		}

		text++;

		namelen = strnlen(text, len - (text - start));

        // Not sure if this should be UTF-8, may only be ASCII
        name = PyUnicode_DecodeUTF8(text, len - (text - start), NULL);
		if (name == NULL) {
			Py_DECREF(ret);
			return NULL;
		}

		if (text + namelen + 20 >= end) {
			PyErr_SetString(PyExc_ValueError, "SHA truncated");
			Py_DECREF(ret);
			Py_DECREF(name);
			return NULL;
		}

        sha = bytes_to_pysha((unsigned char *)text+namelen+1);
        if(sha == NULL) {
			Py_DECREF(ret);
			Py_DECREF(name);
            return NULL;
        }

		item = Py_BuildValue("(NlN)", name, mode, sha);
		if (item == NULL) {
            Py_DECREF(sha);
			Py_DECREF(ret);
			Py_DECREF(name);
			return NULL;
		}
		if (PyList_Append(ret, item) == -1) {
			Py_DECREF(ret);
			Py_DECREF(item);
			return NULL;
		}
		Py_DECREF(item);

		text += namelen+21;
	}

	return ret;
}

struct tree_item {
	char *name;
	int mode;
	PyObject *tuple;
};

int cmp_tree_item(const void *_a, const void *_b)
{
	const struct tree_item *a = _a, *b = _b;
	const char *remain_a, *remain_b;
	int ret, common;
	if (strlen(a->name) > strlen(b->name)) {
		common = strlen(b->name);
		remain_a = a->name + common;
		remain_b = (S_ISDIR(b->mode)?"/":"");
	} else if (strlen(b->name) > strlen(a->name)) {
		common = strlen(a->name);
		remain_a = (S_ISDIR(a->mode)?"/":"");
		remain_b = b->name + common;
	} else { /* strlen(a->name) == strlen(b->name) */
		common = 0;
		remain_a = a->name;
		remain_b = b->name;
	}
	ret = strncmp(a->name, b->name, common);
	if (ret != 0)
		return ret;
	return strcmp(remain_a, remain_b);
}

int cmp_tree_item_name_order(const void *_a, const void *_b) {
	const struct tree_item *a = _a, *b = _b;
	return strcmp(a->name, b->name);
}

static PyObject *py_sorted_tree_items(PyObject *self, PyObject *args)
{
	struct tree_item *qsort_entries = NULL;
	int name_order, num_entries, n = 0, i;
	PyObject *entries, *py_name_order, *ret, *key, *value, *py_mode, *py_sha;
	Py_ssize_t pos = 0;
	int (*cmp)(const void *, const void *);

	if (!PyArg_ParseTuple(args, "OO", &entries, &py_name_order))
		goto error;

	if (!PyDict_Check(entries)) {
		PyErr_SetString(PyExc_TypeError, "Argument not a dictionary");
		goto error;
	}

	name_order = PyObject_IsTrue(py_name_order);
	if (name_order == -1)
		goto error;
	cmp = name_order ? cmp_tree_item_name_order : cmp_tree_item;

	num_entries = PyDict_Size(entries);
	if (PyErr_Occurred())
		goto error;
	qsort_entries = PyMem_New(struct tree_item, num_entries);
	if (!qsort_entries) {
		PyErr_NoMemory();
		goto error;
	}

	while (PyDict_Next(entries, &pos, &key, &value)) {
		if (!PyBytes_Check(key)) {
			PyErr_SetString(PyExc_TypeError, "Name is not a bytes object");
			goto error;
		}

		if (PyTuple_Size(value) != 2) {
			PyErr_SetString(PyExc_ValueError, "Tuple has invalid size");
			goto error;
		}

		py_mode = PyTuple_GET_ITEM(value, 0);
		if (!PyLong_Check(py_mode)) {
			PyErr_SetString(PyExc_TypeError, "Mode is not an integral type");
			goto error;
		}

		py_sha = PyTuple_GET_ITEM(value, 1);
		if(1 != PyObject_IsInstance(py_sha, Sha1Sum)) {
			PyErr_SetString(PyExc_TypeError, "SHA is not a Sha1Sum object");
			goto error;
		}

		qsort_entries[n].name = PyBytes_AS_STRING(key);
		qsort_entries[n].mode = PyLong_AsLong(py_mode);

		PyObject* key_string = PyUnicode_DecodeASCII(PyBytes_AS_STRING(key), PyBytes_Size(key), NULL);
		if(key_string == NULL) {
			goto error;
		}

		if(!PyUnicode_Check(key_string)) {
			PyErr_SetString(PyExc_TypeError, "Unable to convert key to a unicode string");
			Py_DECREF(key_string);
			goto error;
		}

		qsort_entries[n].tuple = PyObject_CallFunctionObjArgs(
		    tree_entry_cls, key_string, py_mode, py_sha, NULL);
		Py_DECREF(key_string);

		if (qsort_entries[n].tuple == NULL) {
			goto error;
		}

		n++;
	}

	qsort(qsort_entries, num_entries, sizeof(struct tree_item), cmp);

	ret = PyList_New(num_entries);
	if (ret == NULL) {
		PyErr_NoMemory();
		goto error;
	}

	for (i = 0; i < num_entries; i++) {
		PyList_SET_ITEM(ret, i, qsort_entries[i].tuple);
	}
	PyMem_Free(qsort_entries);
	return ret;

error:
	for (i = 0; i < n; i++) {
		Py_XDECREF(qsort_entries[i].tuple);
	}
	PyMem_Free(qsort_entries);
	return NULL;
}

static PyMethodDef py_objects_methods[] = {
	{ "parse_tree", (PyCFunction)py_parse_tree, METH_VARARGS | METH_KEYWORDS,
	  NULL },
	{ "sorted_tree_items", py_sorted_tree_items, METH_VARARGS, NULL },
	{ NULL, NULL, 0, NULL }
};

static struct PyModuleDef py_objectsmodule = {
	PyModuleDef_HEAD_INIT,
	"_objects", /* name of module */
	NULL,       /* module documentation, may be NULL */
	-1,         /* size of per-interpreter state of the module,
	               or -1 if the module keeps state in global variables. */
	py_objects_methods
};

PyObject *PyInit__objects(void) {
	PyObject *m, *objects_mod, *errors_mod, *sha_mod;

	m = PyModule_Create(&py_objectsmodule);
	if (m == NULL)
		return NULL;

	errors_mod = PyImport_ImportModule("dulwich.errors");
	if (errors_mod == NULL)
		return NULL;

	object_format_exception_cls = PyObject_GetAttrString(
		errors_mod, "ObjectFormatException");
	Py_DECREF(errors_mod);
	if (object_format_exception_cls == NULL)
		return NULL;

	/* This is a circular import but should be safe since this module is
	 * imported at at the very bottom of objects.py. */
	objects_mod = PyImport_ImportModule("dulwich.objects");
	if (objects_mod == NULL)
		return NULL;

	tree_entry_cls = PyObject_GetAttrString(objects_mod, "TreeEntry");
	Py_DECREF(objects_mod);
	if (tree_entry_cls == NULL)
		return NULL;

	sha_mod = PyImport_ImportModule("dulwich.sha1");
	if (sha_mod == NULL)
		return NULL;

	Sha1Sum = PyObject_GetAttrString(sha_mod, "Sha1Sum");
	Py_DECREF(sha_mod);
	if(Sha1Sum == NULL)
		return NULL;

	return m;
}
