## Demonstrate how components can be replace with fundamental Links and Stores
#
#This notebook demonstrates how generators and storage units can be replaced by more fundamental components, and how their parameters map to each other.

import pypsa, os
import numpy as np
import pandas as pd

from pyomo.environ import Constraint


def replace_gen(network,gen_to_replace):
    """Replace the generator gen_to_replace with a bus for the energy
    carrier, a link for the conversion from the energy carrier to electricity
    and a store to keep track of the depletion of the energy carrier and its
    CO2 emissions."""
    

    gen = network.generators.loc[gen_to_replace]

    if gen["dispatch"] != "flexible":
        raise NotImplementedError("Until time-dependent p_max_pu is introduced for Links, only\
        fully flexible generators can be replaced!")

    bus_name = "{} {}".format(gen["bus"], gen["source"])
    link_name = "{} converter {} to AC".format(gen_to_replace,gen["source"])
    store_name = "{} store {}".format(gen_to_replace,gen["source"])

    network.add("Bus",
            bus_name,
            carrier=gen["source"])

    network.add("Link",
            link_name,
            bus0=bus_name,
            bus1=gen["bus"],
            capital_cost=gen["capital_cost"]*gen["efficiency"],
            s_nom = gen["p_nom"]/gen["efficiency"],
            s_nom_extendable=gen["p_nom_extendable"],
            s_nom_max = gen["p_nom_max"]/gen["efficiency"],
            s_nom_min = gen["p_nom_min"]/gen["efficiency"],
            p_max_pu = gen["p_max_pu_fixed"],
            p_min_pu = gen["p_min_pu_fixed"],
            marginal_cost=gen["marginal_cost"]*gen["efficiency"],
            efficiency=gen["efficiency"])

    network.add("Store",
            store_name,
            bus=bus_name,
            source=gen["source"],
            e_nom_min=-float("inf"),
            e_nom_max=0,
            e_nom_extendable=True,
            e_min_pu_fixed=1.,
            e_max_pu_fixed=0.)

    network.remove("Generator",gen_to_replace)

    return bus_name, link_name, store_name



def replace_su(network,su_to_replace):
    """Replace the storage unit su_to_replace with a bus for the energy
    carrier, two links for the conversion of the energy carrier to and from electricity,
    a store to keep track of the depletion of the energy carrier and its
    CO2 emissions, and a variable generator for the storage inflow.
    
    Because the energy size and power size are linked in the storage unit by the max_hours,
    extra functionality must be added to the LOPF to implement this constraint."""

    su = network.storage_units.loc[su_to_replace]


    if (~pd.isnull(network.storage_units_t.state_of_charge_set[su_to_replace])).any():
        raise NotImplementedError("Until time-dependent e_min_pu and e_max_pu are introduced for Stores, \
        no state_of_charge_set can be set!")

    bus_name = "{} {}".format(su["bus"],su["source"])

    link_1_name = "{} converter {} to AC".format(su_to_replace,su["source"])

    link_2_name = "{} converter AC to {}".format(su_to_replace,su["source"])

    store_name = "{} store {}".format(su_to_replace,su["source"])

    gen_name = "{} inflow".format(su_to_replace)

    network.add("Bus",
            bus_name,
            carrier=su["source"])

    #dispatch link
    network.add("Link",
            link_1_name,
            bus0=bus_name,
            bus1=su["bus"],
            capital_cost=su["capital_cost"]*su["efficiency_dispatch"],
            s_nom = su["p_nom"]/su["efficiency_dispatch"],
            s_nom_extendable=su["p_nom_extendable"],
            s_nom_max = su["p_nom_max"]/su["efficiency_dispatch"],
            s_nom_min = su["p_nom_min"]/su["efficiency_dispatch"],
            p_max_pu = su["p_max_pu_fixed"],
            marginal_cost=su["marginal_cost"]*su["efficiency_dispatch"],
            efficiency=su["efficiency_dispatch"])

    #store link
    network.add("Link",
            link_2_name,
            bus1=bus_name,
            bus0=su["bus"],
            s_nom = su["p_nom"],
            s_nom_extendable=su["p_nom_extendable"],
            s_nom_max = su["p_nom_max"],
            s_nom_min = su["p_nom_min"],
            p_max_pu = -su["p_min_pu_fixed"],
            efficiency=su["efficiency_store"])

    network.add("Store",
            store_name,
            bus=bus_name,
            source=su["source"],
            e_nom=su["p_nom"]*su["max_hours"],
            e_nom_min=su["p_nom_min"]/su["efficiency_dispatch"]*su["max_hours"],
            e_nom_max=su["p_nom_max"]/su["efficiency_dispatch"]*su["max_hours"],
            e_nom_extendable=su["p_nom_extendable"],
            standing_loss=su["standing_loss"],
            e_cyclic=su['cyclic_state_of_charge'],
            e_initial=su['state_of_charge_initial'])

    network.add("Source",
                "rain",
                co2_emissions=0.)

    #inflow from a variable generator, which can be curtailed (i.e. spilled)
    inflow_max = network.storage_units_t.inflow[su_to_replace].max()

    if inflow_max == 0.:
        inflow_pu=0.
    else:
        inflow_pu = network.storage_units_t.inflow[su_to_replace]/inflow_max

    network.add("Generator",
               gen_name,
               bus=bus_name,
               source="rain",
               dispatch="variable",
               p_nom=inflow_max,
               p_max_pu=inflow_pu)

    if su["p_nom_extendable"]:
        ratio2 = su["max_hours"]
        ratio1 = ratio2*su["efficiency_dispatch"]
        def extra_functionality(network,snapshots):
            model = network.model
            model.store_fix_1 = Constraint(rule=lambda model : model.store_e_nom[store_name] == model.branch_s_nom["Link",link_1_name]*ratio1)
            model.store_fix_2 = Constraint(rule=lambda model : model.store_e_nom[store_name] == model.branch_s_nom["Link",link_2_name]*ratio2)

    else:
        extra_functionality=None

    network.remove("StorageUnit",su_to_replace)


    return bus_name, link_1_name, link_2_name, store_name, gen_name, extra_functionality


## Take an example from the git repo which has already been solved

csv_folder_name = os.path.join(os.path.dirname(pypsa.__file__),"../examples/opf-storage-hvdc/opf-storage-data")

results_folder_name = os.path.join(csv_folder_name,"results")

network_r = pypsa.Network(csv_folder_name=results_folder_name)


## Demonstrate that the results are unchanged with replacements

network = pypsa.Network(csv_folder_name=csv_folder_name)

su_to_replace = "Storage 0"

bus_name, link_1_name, link_2_name, store_name, gen_name, extra_functionality = replace_su(network,su_to_replace)

network.lopf(network.snapshots,extra_functionality=extra_functionality,formulation="kirchhoff")

np.testing.assert_almost_equal(network_r.objective,network.objective,decimal=2)

np.testing.assert_array_almost_equal(network_r.storage_units_t.state_of_charge[su_to_replace],network.stores_t.e[store_name])

np.testing.assert_array_almost_equal(network_r.storage_units_t.p[su_to_replace],-network.links_t.p1[link_1_name]-network.links_t.p0[link_2_name])

#check optimised size
np.testing.assert_allclose(network_r.storage_units.at[su_to_replace,"p_nom_opt"],network.links.at[link_2_name,"s_nom_opt"])
np.testing.assert_allclose(network_r.storage_units.at[su_to_replace,"p_nom_opt"],network.links.at[link_1_name,"s_nom_opt"]*network_r.storage_units.at[su_to_replace,"efficiency_dispatch"])



network = pypsa.Network(csv_folder_name=csv_folder_name)

gen_to_replace = "Gas 0"

bus_name, link_name, store_name = replace_gen(network,gen_to_replace)

network.lopf(network.snapshots)


np.testing.assert_allclose(network_r.objective,network.objective)

#check dispatch
np.testing.assert_allclose(-network.links_t.p1[link_name],network_r.generators_t.p[gen_to_replace])

#check optimised size
np.testing.assert_allclose(network_r.generators.at[gen_to_replace,"p_nom_opt"],network.links.at[link_name,"s_nom_opt"]*network.links.at[link_name,"efficiency"])


## Take another example from the git repo which has already been solved

csv_folder_name = os.path.join(os.path.dirname(pypsa.__file__),"../examples/ac-dc-meshed/ac-dc-data")

results_folder_name = os.path.join(csv_folder_name,"results-lopf")

network_r = pypsa.Network(csv_folder_name=results_folder_name)


network = pypsa.Network(csv_folder_name=csv_folder_name)

gen_to_replace = "Frankfurt Gas"

bus_name, link_name, store_name = replace_gen(network,gen_to_replace)

network.lopf(network.snapshots)


np.testing.assert_almost_equal(network_r.objective,network.objective,decimal=5)

np.testing.assert_array_almost_equal(-network.links_t.p1[link_name],network_r.generators_t.p[gen_to_replace])


