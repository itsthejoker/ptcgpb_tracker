import logging

logging.basicConfig(level=logging.DEBUG)


@lambda _: _()
def main():
    print("I RUN ON SCRIPT LOAD!")


# @lambda func: [lambda *args, **kwargs: func(*args, **kwargs), logging.info("Running hello...")][0]
# def hello(name):
#     return f"Hello, {name}!"

factory = lambda arg: [lambda func: [lambda *args, **kwargs: func(arg, **kwargs), logging.info("Running hello...")][0]][0]
bob = factory('bob')

@bob
def hello(name):
    return f"Hello, {name}!"


# def decorator(function):
#     def wrapper(*args, **kwargs):
#         # funny_stuff()
#         # something_with_argument(argument)
#         result = function(*args, **kwargs)
#         # more_funny_stuff()
#         return result
#     return wrapper

print(hello())
