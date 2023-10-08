"""
utility tables for persisting orchestrator state.
currently empty as what needs to be persisted is in flux.
"""
# from sqlalchemy import Column, DateTime, Integer
# from sqlalchemy.orm import declarative_base

# UtilityBase = declarative_base()

#
# def make_last_time_table_class():
#     definition = {
#         "__tablename__": "last_time",
#         "pk": Column(name="pk", type_=Integer, primary_key=True),
#     } | {
#         param.replace("/", "_"): Column(
#             name=param.replace("/", "_"), type_=DateTime(timezone=True)
#         )
#         for param in PARAMETERS_OF_INTEREST
#     }
#     return type("LastTime", (UtilityBase,), definition)
#
#
# LastTime = make_last_time_table_class()
