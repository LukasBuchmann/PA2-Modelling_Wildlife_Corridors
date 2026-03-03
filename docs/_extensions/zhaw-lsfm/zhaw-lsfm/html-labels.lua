-- html-labels.lua
-- Adds language-specific labels for HTML output

function Meta(meta)
  -- Get language, default to English
  local lang = "en"
  if meta.lang then
    lang = pandoc.utils.stringify(meta.lang)
  end

  -- Define labels
  local labels = {}

  if lang == "de" then
    labels = {
      ["zhaw-university"] = "Zürcher Hochschule für Angewandte Wissenschaften",
      ["zhaw-department"] = "Departement Life Sciences und Facility Management",
      ["thesis-type-label"] = "Typ der Arbeit:",
      ["author-label"] = "Autor/in:",
      ["author-by"] = "von",
      ["submission-date-prefix"] = "Abgabedatum",
      ["submission-date-label"] = "Abgabedatum:",
      ["institut-label"] = "Institut:",
      ["degree-label"] = "Studiengang:",
      ["study-direction-prefix"] = "Studienrichtung",
      ["study-direction-label"] = "Studienrichtung:",
      ["supervisors-label"] = "Betreuer / Betreuerinnen:",
      ["keywords-label"] = "Schlüsselwörter:",
      ["status-label"] = "Status:",
      ["confidential-label"] = "Vertraulich"
    }
  else -- default to English
    labels = {
      ["zhaw-university"] = "Zurich University of Applied Sciences",
      ["zhaw-department"] = "Departement Life Sciences and Facility Management",
      ["thesis-type-label"] = "Thesis Type:",
      ["author-label"] = "Author:",
      ["author-by"] = "by",
      ["submission-date-prefix"] = "Submission date",
      ["submission-date-label"] = "Submission Date:",
      ["institut-label"] = "Institut:",
      ["degree-label"] = "Degree:",
      ["study-direction-prefix"] = "Study direction",
      ["study-direction-label"] = "Study Direction:",
      ["supervisors-label"] = "Supervisors:",
      ["keywords-label"] = "Keywords:",
      ["status-label"] = "Status:",
      ["confidential-label"] = "Confidential"
    }
  end

  -- Add labels to metadata
  for key, value in pairs(labels) do
    meta[key] = value
  end

  return meta
end
