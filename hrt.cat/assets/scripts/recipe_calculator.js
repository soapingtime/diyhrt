
//
// NOTE
//
// Recipes listed by weight in grams.
// They are converted to volume in the calculator.
//
//
// we want to take the needed vol of hormone + BB + BA
// then make up the remainder of the volume with oil

const RECIPES = {
  'E_PAR_20': {
    'hormone': 0.02,
    'BB': 0.224,
    'BA': 0.02,
    'oil': 0.73
  },
  'E_PAR_40': {
    'hormone': 0.04,
    'BB': 0.447,
    'BA': 0.02,
    'oil': 0.522
  },
  'T_SLAYBACK_200': {
    'hormone': 0.2,
    'BB': 0.224,
    'BA': 0.02,
    'oil': 0.542
  }
}

//
// Densities
//

const DENSITIES = {
  'E': 1.1,
  'TC': 1.1,
  'TEn': 1.06,
  'TU': 1.03,
  'BB': 1.118,
  'BA': 1.044,
  'none': ''
}

//
//
//

const hormone_select = document.getElementById("hormone-select");
const recipe_select = document.getElementById("recipe-select");
const brew_vol = document.getElementById("brew-vol");

const updateHormoneDensity = () => {
  const hormoneDensityCell = document.getElementById("hormone_density");
  let selectValue = document.getElementById("hormone-select").value;
  hormoneDensityCell.innerText = DENSITIES[selectValue];

  // if everything is filled out, calculate brew amounts.
  if (isFormComplete()) {
    updateRecipe();
  }
}

const updateRecipe = () => {
  // if everything isn't filled out, break.
  if (!isFormComplete()) {
    return;
  }

  const recipeSelectValue = document.getElementById("recipe-select").value;
  const hormoneDensity = DENSITIES[hormone_select.value];

  //
  // Get cells that will receive data
  //
  const hormoneMassCell = document.getElementById("hormone_mass");
  const bbMassCell = document.getElementById("bb_mass");
  const baMassCell = document.getElementById("ba_mass");

  const hormoneVolCell = document.getElementById("hormone_vol");
  const bbVolCell = document.getElementById("bb_vol");
  const baVolCell = document.getElementById("ba_vol");
  const oilVolCell = document.getElementById("oil_vol");

  const hormoneTotalCell = document.getElementById("hormone_total");
  const bbTotalCell = document.getElementById("bb_total");
  const baTotalCell = document.getElementById("ba_total");
  const oilTotalCell = document.getElementById("oil_total");
  //
  //


  const hormoneMass = RECIPES[recipeSelectValue]['hormone'];
  const bbMass = RECIPES[recipeSelectValue]['BB'];
  const baMass = RECIPES[recipeSelectValue]['BA'];

  hormoneMassCell.innerText = hormoneMass * 1000 + "mg";
  bbMassCell.innerText = bbMass * 1000 + "mg";
  baMassCell.innerText = baMass * 1000 + "mg";

  // establish vol of BB and BA and hormone.
  // make up for the remainder of the vol with oil.
  // this makes up for subtle displacements due to
  //    density differences in hormone esters.

  const hormoneIn1ml = convertMassToVol(hormoneMass, hormoneDensity)
  const bbIn1ml = convertMassToVol(bbMass, DENSITIES['BB'])
  const baIn1ml = convertMassToVol(baMass, DENSITIES['BA'])
  const oilIn1ml = Math.round((1 - hormoneIn1ml - bbIn1ml - baIn1ml) * 100) / 100;

  hormoneVolCell.innerText = hormoneIn1ml;
  bbVolCell.innerText = bbIn1ml;
  baVolCell.innerText = baIn1ml;
  oilVolCell.innerText = oilIn1ml;

  const hormoneMassInTotal = hormoneMass * brew_vol.value;
  const hormoneVolInTotal = convertMassToVol(hormoneMassInTotal, hormoneDensity)
  const bbVolInTotal = bbIn1ml * brew_vol.value;
  const baVolInTotal = baIn1ml * brew_vol.value;

  hormoneTotalCell.innerText = Math.round(hormoneMassInTotal * 100) / 100 + 'g / ' + hormoneVolInTotal + 'mL';
  bbTotalCell.innerText = Math.round(bbVolInTotal * 100) / 100 + 'mL';
  baTotalCell.innerText = Math.round(baVolInTotal * 100) / 100 + 'mL';
  oilTotalCell.innerText = Math.round((brew_vol.value - hormoneVolInTotal - bbVolInTotal - baVolInTotal) * 100) / 100 + 'mL';
}

hormone_select.addEventListener('change', updateHormoneDensity);
recipe_select.addEventListener('change', updateRecipe);
brew_vol.addEventListener('change', updateRecipe);

const convertMassToVol = (mass, density) => {
  return Math.round(mass/density * 100) / 100;
}

const isFormComplete = () => {
  const hormone_select = document.getElementById("hormone-select").value;
  const recipe_select = document.getElementById("recipe-select").value;
  const brewVol = document.getElementById("brew-vol").value;

  return (hormone_select !== 'none' &&
      recipe_select !== 'none' && brewVol !== "")
}
