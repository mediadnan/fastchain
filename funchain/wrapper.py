import functools
import types
import warnings
from inspect import getfullargspec, isfunction, isclass, isbuiltin, ismethod
import typing
from typing import (
    Any,
    Callable,
    Optional,
    TypeAlias,
    overload,
    Tuple,
)

from funchain.tools import validate

NOT_SPECIFIED = object()
CHAINABLE_FUNC: TypeAlias = Callable[[Any], Any]


def get_name(func: Callable, title: str = ...) -> str:
    """validates the name if passed or the function's __qualname__"""
    if title is not ...:
        return validate(title, 'title', str, True)
    return func.__qualname__ if hasattr(func, '__qualname__') else type(func).__qualname__


def get_signature(func: CHAINABLE_FUNC) -> Optional[Tuple[Any, Any]]:
    """verifies and gets the function's signature, enforces (Any) -> Any ."""
    if not callable(func):
        raise TypeError(f"{get_signature.__name__} takes a callable as parameter")

    try:
        spec = getfullargspec(func)
    except (ValueError, TypeError):
        return NOT_SPECIFIED, NOT_SPECIFIED

    i = 0 if (
        isfunction(func) or
        isclass(func) or
        isbuiltin(func) or  # for builtin methods and functions
        not ismethod(getattr(func, '__call__', None))  # for @staticmethod __call__
    ) else 1    # 1 ignores first parameter 'self' or 'cls' on checks

    # validate function's parameters
    required_args = len(spec.args or ()) - len(spec.defaults or ())
    required_kwargs = len(spec.kwonlyargs or ()) - len(spec.kwonlydefaults or ())
    if not (len(spec.args) > i or spec.varargs):
        raise ValueError("chainable functions must take one argument")
    elif not (required_args < (2 + i) and required_kwargs == 0):
        raise ValueError("chainable functions must only take one required positional argument")

    arg_ann = spec.annotations.get(spec.args[i] if len(spec.args) > i else spec.varargs, NOT_SPECIFIED)
    return_ann = spec.annotations.get('return', NOT_SPECIFIED)

    # check function's return
    if return_ann in {None, type(None)}:
        warnings.warn(
            f"chainable functions are expected to return a value, {func!r} is promising None",
            category=UserWarning,
            stacklevel=2
        )

    return arg_ann, return_ann


def pretty_annotation(annotation) -> str:
    """prettifies annotations"""
    if annotation is NOT_SPECIFIED:
        return '?'
    elif annotation is Ellipsis:
        return '...'
    elif annotation is type(None):
        return 'None'
    elif type(annotation) is typing._UnionGenericAlias:  # Type: ignore
        return ' | '.join(map(pretty_annotation, annotation.__args__))
    elif type(annotation) is typing._CallableGenericAlias:  # Type: ignore
        *args_type, return_type = annotation.__args__
        args_type = ', '.join(map(pretty_annotation, args_type))
        return f'({pretty_annotation(args_type)}) -> {pretty_annotation(return_type)}'
    elif isinstance(annotation, (typing._GenericAlias, types.GenericAlias)):  # Type: ignore
        origin = pretty_annotation(annotation.__origin__)
        args = ', '.join(map(pretty_annotation, annotation.__args__))
        return f'{origin}[{args}]'
    elif isinstance(annotation, typing._BaseGenericAlias):  # Type: ignore
        return pretty_annotation(annotation.__origin__)
    elif isinstance(annotation, typing._SpecialForm):  # Type: ignore
        return annotation._name
    elif isinstance(annotation, type):
        return annotation.__name__
    return str(annotation)


class Wrapper:
    __name: str
    __name_sig: str
    __input: Any
    __output: Any
    __func: Callable[['Wrapper', Any], Any]
    __default: Any

    def __init__(
            self,
            function: CHAINABLE_FUNC,
            *,
            title: str = ...,
            default: Any = None
    ) -> None:
        """
        Wrapper objects are callables objects that validate function signatures (Any) -> Any,
        cache input and output annotations if there's any, rename functions, stores a default value.

        It is not a good practice to create Wrapper objects directly,
        but rather use chainable or funfact decorators to do so.

        :param function: function or a callable object with a signature (Any) -> Any
        :param title: the name to identify this function (optional, default: func.__qualname__)
        :param default: the value to be returned at failures (optional, default: None)
        """
        if not callable(function):
            raise TypeError(f"{type(function)} is not a function")
        self.__input, self.__output = get_signature(function)
        self.__name = get_name(function, title)
        self.__name_sig = f'{self.__name}({pretty_annotation(self.__input)}) -> {pretty_annotation(self.__output)}'
        self.__doc__ = function.__doc__
        self.__func = function
        self.__default = default

    @property
    def name(self) -> str:
        """the name given to the function - read-only"""
        return self.__name

    @property
    def default(self) -> Any:
        """the value to be returned when failing - read-only"""
        return self.__default

    @property
    def function(self) -> CHAINABLE_FUNC:
        """the wrapped function - read-only"""
        return self.__func

    def __repr__(self) -> str:
        return self.__name_sig

    def __call__(self, arg) -> Any:
        return self.__func(arg)


@overload
def chainable(function: CHAINABLE_FUNC, /, *, title: str = None, default: Any = None) -> Wrapper: ...
@overload
def chainable(*, title: str = None, default: Any = None) -> Callable[[CHAINABLE_FUNC], Wrapper]: ...


def chainable(function: CHAINABLE_FUNC = None, /, *, title: str = ..., default: Any = None):
    """
    wraps a function and returns a Wrapper object used by chains to create the right component,
    it can be used as a decorator or as a function wrapper.

    Wrapper objects are callables objects that validate function signatures (Any) -> Any,
    cache input and output annotations if there's any, rename functions, stores a default value


    :param function: function or a callable object with a signature (Any) -> Any
    :param title: the name to identify this function (default: func.__qualname__)
    :param default: the value to be returned at failures (default: None)

    USAGE:

    >>> @chainable
    ... def function(arg):
    ...     pass

    >>> @chainable(title="my_function", default=0)
    ... def function(arg):
    ...     pass

    or

    >>> def function(arg):
    ...     pass

    >>> func = chainable(function)
    >>> my_func = chainable(function, title="my_func", default='')
    """
    if function is None:
        def decorator(decorated: CHAINABLE_FUNC):
            return chainable(decorated, title=title, default=default)

        return decorator
    return Wrapper(function, title=title, default=default)


def funfact(func: CHAINABLE_FUNC):
    """
    decorates higher order functions that returns functions with
    (Any) -> Any signature, or classes of callable object with that signature.

    it returns a similar function (constructor) with additional parameters 'title'
    and 'default', this returned function when called returns a Wrapper object
    over the returned callable.

    :param func: function that returns a callable function.
    :return: function that returns a Wrapper object.

    USAGE:

    >>> @funfact
    ... def hof(*args, **kwargs):
    ...     def func(a): ...
    ...     return func

    >>> my_func = hof(4, 3, 1, title='my_func', default=0)
    """
    @functools.wraps(func)
    def wrapper(
            *args,
            title: str = ...,
            default: Any = None,
            **kwargs
    ) -> Wrapper:
        return Wrapper(
            func(*args, **kwargs),
            title=get_name(func, title),
            default=default
        )
    return wrapper